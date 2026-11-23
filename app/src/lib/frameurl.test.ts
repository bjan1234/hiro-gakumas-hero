import { expect, test } from "bun:test";
import { frameUrl } from "./hiro";

test("frameUrl 认对局 trace 和任务目录（初 / N.I.A）两种截图路径，别的不认", () => {
  expect(frameUrl("/h/work/traces/j1/frames/00001.jpg")).toContain("traces/j1/frames/00001.jpg");
  expect(frameUrl("/h/jobs/j2/frames/00081-195535-opening.jpg")).toContain("jobs/j2/frames/00081-195535-opening.jpg");
  expect(frameUrl("/h/jobs/j2/events.jsonl")).toBeNull();
  expect(frameUrl(null)).toBeNull();
});
