/**
 * Browser UI test using playwright-core against the running server.
 * Verifies: session creation, message send, streaming render, approval
 * card, approve flow, tool result render, final answer, history reload.
 */
import { chromium } from "playwright-core";

const BASE = "http://127.0.0.1:3080";
const SHOT = (n) => `/tmp/ui-${n}.png`;

const browser = await chromium.launch({
  executablePath: "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
  args: ["--no-sandbox"],
});
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
page.on("dialog", (d) => d.accept(""));   // cwd prompt -> auto workspace
page.on("console", (m) => {
  if (m.type() === "error") console.log("PAGE ERROR:", m.text());
});
page.on("pageerror", (e) => console.log("PAGE EXCEPTION:", e.message));

await page.goto(BASE);
await page.waitForSelector("#model-badge");
console.log("model badge:", await page.textContent("#model-badge"));

// create session
await page.click("#btn-new");
await page.waitForSelector(".session-item.active", { timeout: 5000 });
console.log("session created:", await page.textContent("#session-cwd"));

// send a message
await page.fill("#input", "帮我跑一下 echo 测试");
await page.click("#btn-send");

// expect approval card
await page.waitForSelector(".approval", { timeout: 30000 });
console.log("approval card shown");
await page.screenshot({ path: SHOT("1-approval"), fullPage: false });

// approve
await page.click("#btn-approve");
// wait for tool result ✓ and final text
await page.waitForFunction(
  () => document.querySelector(".tool-card .tool-status")?.textContent?.includes("✓"),
  { timeout: 30000 }
);
await page.waitForFunction(
  () => [...document.querySelectorAll(".msg.assistant .content")].some((e) =>
    e.textContent.includes("工具结果")),
  { timeout: 30000 }
);
console.log("tool executed and final answer rendered");

// open tool card to show result
await page.click(".tool-card .tool-head");
await page.screenshot({ path: SHOT("2-done"), fullPage: false });

// reload -> history restore
await page.reload();
await page.waitForSelector(".session-item", { timeout: 5000 });
await page.click(".session-item");
await page.waitForSelector(".tool-card", { timeout: 5000 });
const msgs = await page.$$eval(".msg", (els) => els.length);
console.log("history restored, msg blocks:", msgs);
await page.screenshot({ path: SHOT("3-restored"), fullPage: false });

await browser.close();
console.log("UI TEST PASSED");
process.exit(0);
