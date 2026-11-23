// 驾驶舱（设计简报 §5）：实时画面 + 步骤时间线（理由 + 谁定的）；右边状态和控制；结束后成绩条和复盘。
// 看的人只想知道三件事：打到哪了、刚做了什么、要不要我管。
import { ArrowLeft } from "lucide-react";
import { useEffect, useState } from "react";
import { JobControls, JobFrame, ReviewButton, ScoreStrip, StatePill, StepRow, lastReport } from "../components/Job";
import { KIND_LABEL, clock, elapsed, logText, pageLabel } from "../lib/labels";
import type { JobEvent } from "../lib/hiro";
import { useJob } from "../lib/useJob";

/** 步骤出来之前（开局三步、扫描）给人看的进展：日志去掉前缀，最近几条。 */
const QUIET = new Set(["step", "report", "frame", "start"]);

function useNow(live: boolean): number {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    if (!live) return;
    const t = setInterval(() => setNow(Date.now() / 1000), 15_000);
    return () => clearInterval(t);
  }, [live]);
  return now;
}

export function Cockpit({ jobId, onBack }: { jobId: string; onBack: () => void }) {
  const { job, state, steps, events, lastFrame, refresh } = useJob(jobId);
  const live = state === "running" || state === "paused" || state === "takeover" || state === "stopping";
  const now = useNow(live);
  const feed = [...steps].reverse().slice(0, 60);
  const notes = events.filter((e) => !QUIET.has(e.type) && logText(e.text));
  const tail = notes[notes.length - 1];
  const exams = lastReport(events);
  const pausable = job?.pausable !== false;
  const title = job?.summary ?? KIND_LABEL[job?.kind ?? ""] ?? "对局";
  const started = job?.started_at;
  const ended = job?.ended_at ?? null;
  return (
    <div className="flex min-h-0 min-w-0 flex-1 bg-surface">
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 flex-none items-center gap-3 border-b border-line px-6">
          <button
            type="button"
            className="inline-flex h-8 flex-none items-center gap-1 rounded-md px-2 -ml-2 text-[12.5px] whitespace-nowrap text-ink-2 hover:bg-surface-2 hover:text-ink focus-visible:ring-2 focus-visible:ring-brand-soft focus-visible:outline-none"
            onClick={onBack}
            aria-label="返回对话"
          >
            <ArrowLeft className="size-4" />
            返回
          </button>
          <h1 className="m-0 min-w-0 flex-1 truncate text-[15px] font-semibold" title={title}>
            {title}
          </h1>
          <StatePill state={state} />
        </header>
        <div className="flex min-h-0 flex-1 gap-6 px-6 py-5">
          <JobFrame frame={lastFrame} live={live} className="w-[clamp(180px,34%,300px)] self-start" />
          <div className="flex min-w-0 flex-1 flex-col">
            {exams && (
              <section className="mb-4 rounded-xl border border-line bg-surface-2 px-4 py-3.5">
                <div className="mb-2 flex items-center justify-between">
                  <span className="text-[12px] font-medium text-ink-2">成绩</span>
                  <ReviewButton jobId={jobId} />
                </div>
                <ScoreStrip exams={exams} />
              </section>
            )}
            {!exams && !live && state && (
              <div className="mb-4 flex items-center justify-between gap-3 rounded-xl border border-line bg-surface-2 px-4 py-3">
                <span className={state === "failed" || state === "lost" ? "text-critical" : "text-ink-2"}>{logText(tail?.text) || "这局已经结束"}</span>
                {steps.length > 0 && <ReviewButton jobId={jobId} />}
              </div>
            )}
            <h2 className="m-0 mb-1 text-[12px] font-medium text-ink-3">{feed.length ? "初星助手每一步做了什么" : "准备中"}</h2>
            <ol className="m-0 min-h-0 flex-1 list-none divide-y divide-line overflow-auto p-0 pr-1">
              {feed.length === 0 && <Notes notes={notes} live={live} />}
              {feed.map((e, i) => (
                <StepRow key={e.seq} e={e} now={i === 0 && live} />
              ))}
            </ol>
          </div>
        </div>
      </div>
      <aside className="flex w-[240px] flex-none flex-col gap-6 border-l border-line bg-surface-2 px-5 py-5">
        <section>
          <h3 className="m-0 mb-2.5 text-[12px] font-medium text-ink-3">现在</h3>
          <dl className="m-0 grid grid-cols-[auto_1fr] items-baseline gap-x-3 gap-y-2 text-[12.5px]">
            <dt className="text-ink-3">页面</dt>
            <dd className="m-0 truncate text-right font-medium">{steps.length ? pageLabel(steps[steps.length - 1]?.page) : live ? "开局准备" : "—"}</dd>
            <dt className="text-ink-3">步数</dt>
            <dd className="disp m-0 text-right text-[17px] leading-none">{steps.length}</dd>
            {started ? (
              <>
                <dt className="text-ink-3">{live ? "已打" : "用时"}</dt>
                <dd className="m-0 text-right tabular-nums">{elapsed(started, ended ?? now)}</dd>
              </>
            ) : null}
          </dl>
          {tail && (
            <p className="m-0 mt-3 border-t border-line pt-3 text-[12px] leading-relaxed text-ink-2">
              <span className="mr-1.5 text-ink-3 tabular-nums">{clock(tail.t)}</span>
              {logText(tail.text)}
            </p>
          )}
        </section>
        <section>
          <h3 className="m-0 mb-2.5 text-[12px] font-medium text-ink-3">操作</h3>
          {live ? <JobControls jobId={jobId} state={state} pausable={pausable} onDone={refresh} /> : <p className="m-0 text-[12px] text-ink-3">这局已经结束</p>}
        </section>
      </aside>
    </div>
  );
}

function Notes({ notes, live }: { notes: JobEvent[]; live: boolean }) {
  const last = notes.slice(-6).reverse();
  if (!last.length) return <li className="py-6 text-ink-3">{live ? "正在连游戏…" : "还没有步骤"}</li>;
  return (
    <>
      {last.map((e, i) => (
        <li key={e.seq} className="grid grid-cols-[44px_1fr] gap-x-3 py-2.5">
          <span className="pt-px text-right text-[11.5px] text-ink-3 tabular-nums">{i === 0 && live ? "现在" : clock(e.t)}</span>
          <span className={i === 0 ? "text-[13px] text-ink" : "text-[12.5px] text-ink-2"}>{logText(e.text)}</span>
        </li>
      ))}
    </>
  );
}
