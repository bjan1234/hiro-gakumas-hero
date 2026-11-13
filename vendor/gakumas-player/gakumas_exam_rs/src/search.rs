//! 实战出牌搜索（任务 ②，设计稿 docs/ryugi/specs/2026-11-12-rust-exam-search-design.md 第 2、3 部分）。
//!
//! - `sample_world`：只重排画面看不到的部分——对局随机数、山札顺序（已公开的顶部几张保留）、未见回合的属性（在给定的回合之间
//!   互换，所以属性的总配额不变）；手牌、弃牌、除外、状态、附魔、分数等可见部分不动。
//! - `gnrpa`：Generalized Nested Rollout Policy Adaptation（Cazenave 2020，在 NRPA（Rosin 2011）上加了偏置 β），按论文自己写，
//!   不来自任何现成实现。策略是「动作编码 → 权重」表，续打时按 softmax(w/τ + β) 抽动作；每层迭代后按本层最好路线调整权重。
//! - `search`：W 个世界并行各跑 GNRPA（线程池，到时间就停），每个世界取最好路线的第一手投票，平票比平均终局分。
//!
//! 搜索只在随机补全出来的世界里进行，不读种子、不读存档的隐藏信息（项目规矩）。

use crate::exam::{Action, Exam};
use rustc_hash::FxHashMap;
use std::time::{Duration, Instant};

/// 画面看不到、要重排的部分（Python 侧建起点时给）。
#[derive(Clone, Debug, Default)]
pub struct Hidden {
    /// 山札顶部已公开的张数（检索 / 预览看到的），这几张顺序保留
    pub known_deck_prefix: usize,
    /// 属性没看到的回合（turn_types 的下标，0 起）：它们之间互换，保持本场配额
    pub free_turns: Vec<usize>,
}

/// 搜索用的随机数（splitmix64），和对局随机数分开，不影响引擎规则。
#[derive(Clone, Copy, Debug)]
pub struct Rng(u64);

impl Rng {
    pub fn new(seed: u64) -> Self {
        Rng(seed ^ 0x9E37_79B9_7F4A_7C15)
    }
    #[inline]
    pub fn next_u64(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        z ^ (z >> 31)
    }
    /// [0, n)
    #[inline]
    pub fn below(&mut self, n: usize) -> usize {
        ((self.next_u64() as u128 * n as u128) >> 64) as usize
    }
    /// [0, 1)
    #[inline]
    pub fn unit(&mut self) -> f64 {
        (self.next_u64() >> 11) as f64 / (1u64 << 53) as f64
    }
    pub fn shuffle<T>(&mut self, v: &mut [T]) {
        for k in (1..v.len()).rev() {
            let j = self.below(k + 1);
            v.swap(j, k);
        }
    }
}

/// 一个世界：克隆局面，重排看不到的部分。
pub fn sample_world(ex: &Exam, hidden: &Hidden, seed: u64) -> Exam {
    let mut w = ex.clone();
    let mut r = Rng::new(seed);
    let mut state = (r.next_u64() & 0xffff_ffff) as u32;
    if state == 0 {
        state = 0x6d2b_79f5; // xorshift 的 0 状态会卡死
    }
    w.rng.state = state;
    let k = hidden.known_deck_prefix.min(w.deck.len());
    r.shuffle(&mut w.deck[k..]);
    let idx: Vec<usize> = hidden.free_turns.iter().copied().filter(|&i| i < w.turn_types.len()).collect();
    let mut vals: Vec<i64> = idx.iter().map(|&i| w.turn_types[i]).collect();
    r.shuffle(&mut vals);
    for (&i, v) in idx.iter().zip(vals) {
        w.turn_types[i] = v;
    }
    w
}

/// GNRPA 参数（缺省按论文：α = 1、τ = 1；层数 / 迭代数按 15 秒预算粗定，bench 冒烟时再调）。
#[derive(Clone, Debug)]
pub struct Params {
    pub level: u32,
    pub iterations: u32,
    pub alpha: f64,
    pub temperature: f64,
    /// 「结束回合」的偏置 β（负数 = 还有牌能打时少结束；0 = 不偏）
    pub end_bias: f64,
    /// 一次续打最多走几步（防死循环）
    pub max_steps: usize,
}

impl Default for Params {
    fn default() -> Self {
        Params { level: 2, iterations: 60, alpha: 1.0, temperature: 1.0, end_bias: -1.0, max_steps: 600 }
    }
}

/// 动作编码：(回合, 本回合第几手, 动作种类, 卡 / 饮料 id, 强化)。同一个编码在不同续打里代表「同一个决定」，权重共享。
fn code(ex: &Exam, a: Action) -> u64 {
    let (kind, obj, up) = match a {
        Action::Play(i) => {
            let c = &ex.cards[ex.hand[i]];
            (1u64, c.card_id as u64, c.upgrade() as u64)
        }
        Action::Drink(i) => (2u64, ex.drinks[i] as u64, 0),
        Action::End => (3u64, 0, 0),
    };
    let t = ex.current_turn.max(0) as u64;
    let n = ex.turn_card_play_count.max(0) as u64;
    (t << 52) ^ (n << 46) ^ (kind << 44) ^ (up << 40) ^ obj
}

fn bias(a: Action, p: &Params, n_legal: usize) -> f64 {
    match a {
        Action::End if n_legal > 1 => p.end_bias,
        _ => 0.0,
    }
}

/// 一条路线：每一步的 (候选编码, 偏置, 选了第几个)，调权重时不用重放局面。
#[derive(Clone, Default)]
pub struct Line {
    pub score: i64,
    pub first: Option<Action>,
    steps: Vec<(Vec<u64>, Vec<f64>, usize)>,
}

type Policy = FxHashMap<u64, f64>;

fn playout(root: &Exam, pol: &Policy, p: &Params, rng: &mut Rng) -> Line {
    let mut ex = root.clone();
    let mut line = Line::default();
    let mut probs: Vec<f64> = vec![];
    for _ in 0..p.max_steps {
        ex.advance();
        if ex.ended {
            break;
        }
        let acts = ex.legal_actions();
        if acts.is_empty() {
            break;
        }
        let codes: Vec<u64> = acts.iter().map(|&a| code(&ex, a)).collect();
        let bs: Vec<f64> = acts.iter().map(|&a| bias(a, p, acts.len())).collect();
        probs.clear();
        let mut mx = f64::NEG_INFINITY;
        for (c, b) in codes.iter().zip(&bs) {
            let v = pol.get(c).copied().unwrap_or(0.0) / p.temperature + b;
            probs.push(v);
            mx = mx.max(v);
        }
        let mut tot = 0.0;
        for v in probs.iter_mut() {
            *v = (*v - mx).exp();
            tot += *v;
        }
        let mut x = rng.unit() * tot;
        let mut k = probs.len() - 1;
        for (i, v) in probs.iter().enumerate() {
            if x < *v {
                k = i;
                break;
            }
            x -= v;
        }
        if line.first.is_none() {
            line.first = Some(acts[k]);
        }
        ex.step(acts[k]);
        line.steps.push((codes, bs, k));
    }
    ex.advance();
    line.score = ex.score;
    line
}

/// 按最好路线调权重：选中的 +α，每步所有候选按当前概率 −α·π（论文的 Adapt，含偏置）。
fn adapt(pol: &Policy, best: &Line, p: &Params) -> Policy {
    let mut out = pol.clone();
    for (codes, bs, k) in &best.steps {
        let mut ws: Vec<f64> = codes.iter().zip(bs).map(|(c, b)| pol.get(c).copied().unwrap_or(0.0) / p.temperature + b).collect();
        let mx = ws.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
        let mut tot = 0.0;
        for w in ws.iter_mut() {
            *w = (*w - mx).exp();
            tot += *w;
        }
        for (i, c) in codes.iter().enumerate() {
            let d = ws[i] / tot;
            *out.entry(*c).or_insert(0.0) -= p.alpha / p.temperature * d;
        }
        *out.entry(codes[*k]).or_insert(0.0) += p.alpha / p.temperature;
    }
    out
}

/// 嵌套搜索；到 deadline 就返回目前最好的路线。
pub fn gnrpa(root: &Exam, level: u32, pol: &Policy, p: &Params, rng: &mut Rng, deadline: Instant, playouts: &mut u64) -> Line {
    if level == 0 {
        *playouts += 1;
        return playout(root, pol, p, rng);
    }
    let mut best = Line { score: i64::MIN, ..Default::default() };
    let mut pol = pol.clone();
    for _ in 0..p.iterations {
        let r = gnrpa(root, level - 1, &pol, p, rng, deadline, playouts);
        if r.score >= best.score {
            best = r;
        }
        if Instant::now() >= deadline {
            break;
        }
        pol = adapt(&pol, &best, p);
    }
    best
}

/// 一个世界的结果。
#[derive(Clone, Debug)]
pub struct WorldResult {
    pub first: Option<Action>,
    pub score: i64,
    pub playouts: u64,
    /// 顶层至少跑完了一整轮（false = 第一轮就被时间截断，路线没充分搜）
    pub complete: bool,
}

/// 搜索总结果：各第一手的票数和平均终局分，按（票数，平均分）从高到低。
#[derive(Clone, Debug)]
pub struct SearchResult {
    pub best: Option<Action>,
    pub votes: Vec<(Action, usize, f64)>,
    pub worlds: Vec<WorldResult>,
    pub elapsed: Duration,
}

fn run_world(w: Exam, p: &Params, seed: u64, deadline: Instant) -> WorldResult {
    let mut rng = Rng::new(seed.wrapping_mul(0x2545_F491_4F6C_DD1D));
    let mut n = 0u64;
    // 顶层跑完一轮还有时间：从空策略重新跑一轮（换随机数），留最好的路线（预算用满，不提前交卷）
    let mut best = gnrpa(&w, p.level, &Policy::default(), p, &mut rng, deadline, &mut n);
    let mut rounds = 1;
    while Instant::now() < deadline {
        let r = gnrpa(&w, p.level, &Policy::default(), p, &mut rng, deadline, &mut n);
        if r.score > best.score {
            best = r;
        }
        rounds += 1;
    }
    WorldResult { first: best.first, score: best.score, playouts: n, complete: rounds > 1 }
}

/// W 个世界并行各跑 GNRPA，第一手投票。threads = 0 时用「CPU 核数 − 1」（至少 1）。
/// 局面已经结束 / 没有决定可做时 best = None；一个世界都没出第一手时 best = None（Python 退回 UINet）。
pub fn search(ex: &Exam, hidden: &Hidden, worlds: usize, seconds: f64, threads: usize, seed: u64, p: &Params) -> SearchResult {
    let t0 = Instant::now();
    let deadline = t0 + Duration::from_secs_f64(seconds.max(0.0));
    let mut root = ex.clone();
    root.advance();
    if root.ended || root.legal_actions().len() <= 1 {
        let only = if root.ended { None } else { root.legal_actions().first().copied() };
        return SearchResult { best: only, votes: only.map(|a| vec![(a, 0, 0.0)]).unwrap_or_default(), worlds: vec![], elapsed: t0.elapsed() };
    }
    let threads = if threads == 0 {
        std::thread::available_parallelism().map(|n| n.get().saturating_sub(1)).unwrap_or(1).max(1)
    } else {
        threads
    };
    let jobs: Vec<(usize, Exam)> = (0..worlds.max(1)).map(|i| (i, sample_world(&root, hidden, seed.wrapping_add(i as u64 * 7_919)))).collect();
    let mut results: Vec<Option<WorldResult>> = vec![None; jobs.len()];
    let chunks: Vec<Vec<(usize, Exam)>> = {
        let mut c: Vec<Vec<(usize, Exam)>> = (0..threads.min(jobs.len())).map(|_| vec![]).collect();
        let n = c.len();
        for (k, j) in jobs.into_iter().enumerate() {
            c[k % n].push(j);
        }
        c
    };
    std::thread::scope(|s| {
        let hs: Vec<_> = chunks
            .into_iter()
            .map(|chunk| {
                let p = p.clone();
                s.spawn(move || {
                    // 一个线程负责几个世界：剩余时间平分给还没跑的世界
                    let n = chunk.len();
                    let mut out = vec![];
                    for (k, (i, w)) in chunk.into_iter().enumerate() {
                        let now = Instant::now();
                        let left = deadline.saturating_duration_since(now);
                        let dl = now + left / (n - k) as u32;
                        out.push((i, run_world(w, &p, seed ^ (i as u64) << 20, dl)));
                    }
                    out
                })
            })
            .collect();
        for h in hs {
            for (i, r) in h.join().expect("搜索线程 panic") {
                results[i] = Some(r);
            }
        }
    });
    let worlds: Vec<WorldResult> = results.into_iter().flatten().collect();
    let mut tally: Vec<(Action, usize, f64)> = vec![];
    for w in &worlds {
        if let Some(a) = w.first {
            match tally.iter_mut().find(|(b, _, _)| *b == a) {
                Some(t) => {
                    t.2 = (t.2 * t.1 as f64 + w.score as f64) / (t.1 + 1) as f64;
                    t.1 += 1;
                }
                None => tally.push((a, 1, w.score as f64)),
            }
        }
    }
    tally.sort_by(|a, b| b.1.cmp(&a.1).then(b.2.partial_cmp(&a.2).unwrap_or(std::cmp::Ordering::Equal)));
    SearchResult { best: tally.first().map(|t| t.0), votes: tally, worlds, elapsed: t0.elapsed() }
}
