import { expect, test } from "bun:test";
import { elapsed, logText } from "./labels";

test("logText 去掉日志行的时间、级别和模块名，只留中文说明", () => {
  expect(logText("[2026-11-23 19:52:24,843] [INFO] [hiro.runtime.finish] 结算画面已点完，回到首页")).toBe("结算画面已点完，回到首页");
  expect(logText("[2026-11-23 19:55:35,905] [ERROR] [__main__] 租借格挑不到合适的卡，停下")).toBe("租借格挑不到合适的卡，停下");
  expect(logText("已开始")).toBe("已开始");
  expect(logText(undefined)).toBe("");
});

test("elapsed 写成几分钟 / 几小时几分", () => {
  expect(elapsed(1000, 1000 + 40)).toBe("不到 1 分钟");
  expect(elapsed(1000, 1000 + 12 * 60 + 5)).toBe("12 分钟");
  expect(elapsed(1000, 1000 + 75 * 60)).toBe("1 小时 15 分");
});
