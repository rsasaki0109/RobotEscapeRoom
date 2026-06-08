// Headless 3D render of the Robot Escape Room MCAP for the README hero.
// Same pipeline as render.cjs, camera framed on the wider escape facility.

const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const FRAMES_DIR = process.argv[2] || "/tmp/erframes";
const BASE_URL = process.argv[3] || "http://localhost:8080";
const MCAP_URL = process.argv[4] || `${BASE_URL}/escape_room.mcap`;

const SPEED = Number(process.env.SPEED || 0.35);
const CAPTURE_MS = Number(process.env.CAPTURE_MS || 55000);
const WIDTH = Number(process.env.WIDTH || 1920);
const HEIGHT = Number(process.env.HEIGHT || 1080);

function heroLayout() {
  const panel = {
    layers: {
      grid1: {
        visible: true, frameLocked: true, label: "Grid", instanceId: "grid1",
        layerId: "foxglove.Grid", size: 32, divisions: 32, lineWidth: 0.8,
        color: "#1e4a7a", position: [14, 0, -0.08], rotation: [0, 0, 0], order: 1,
      },
    },
    cameraState: {
      distance: 34, perspective: true, phi: 56,
      target: [0, 0, 0], targetOffset: [14, 0, 4.5],
      targetOrientation: [0, 0, 0, 1], thetaOffset: 18, fovy: 42, near: 0.5, far: 5000,
    },
    followMode: "follow-none",
    followTf: "map",
    scene: { backgroundColor: "#0d1b33", transforms: { showLabel: false, axisScale: 0, lineWidth: 0 } },
    transforms: {},
    topics: { "/semantic_toponav/scene": { visible: true } },
    publish: {
      type: "point", poseTopic: "/move_base_simple/goal", pointTopic: "/clicked_point",
      poseEstimateTopic: "/initialpose", poseEstimateXDeviation: 0.5,
      poseEstimateYDeviation: 0.5, poseEstimateThetaDeviation: 0.26179939,
    },
    imageMode: {},
  };
  return {
    configById: { "3D!escape": panel },
    globalVariables: {}, userNodes: {},
    playbackConfig: { speed: SPEED },
    layout: "3D!escape",
  };
}

async function injectLayout(page, data) {
  await page.evaluate(async (newData) => {
    await new Promise((resolve, reject) => {
      const req = indexedDB.open("lichtblick-layouts");
      req.onerror = () => reject(new Error("cannot open lichtblick-layouts"));
      req.onsuccess = () => {
        const db = req.result;
        const tx = db.transaction("layouts", "readwrite");
        const store = tx.objectStore("layouts");
        const all = store.getAll();
        all.onsuccess = () => {
          const rec = all.result[0];
          if (!rec) return reject(new Error("no layout record"));
          rec.layout.baseline.data = newData;
          rec.layout.baseline.savedAt = new Date().toISOString();
          rec.layout.working = null;
          store.put(rec).onsuccess = () => resolve();
        };
      };
    });
  }, data);
}

(async () => {
  fs.rmSync(FRAMES_DIR, { recursive: true, force: true });
  fs.mkdirSync(FRAMES_DIR, { recursive: true });

  const browser = await chromium.launch({
    channel: "chrome",
    headless: true,
    args: ["--use-gl=angle", "--use-angle=swiftshader", "--no-sandbox", "--force-color-profile=srgb"],
  });
  const ctx = await browser.newContext({ viewport: { width: WIDTH, height: HEIGHT }, deviceScaleFactor: 1 });
  const page = await ctx.newPage();

  await page.goto(BASE_URL + "/", { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForTimeout(5000);
  await injectLayout(page, heroLayout());

  const url = `${BASE_URL}/?ds=remote-file&ds.url=${encodeURIComponent(MCAP_URL)}`;
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForTimeout(16000);

  const hide = await page.$('button[aria-label="Hide left sidebar"]');
  if (hide) await hide.click();
  await page.addStyleTag({ content: ".mui-1b64mk4-root{display:none !important;}" });
  await page.waitForTimeout(1200);

  const box = await (await page.$("canvas")).boundingBox();
  const clip = {
    x: Math.round(box.x), y: Math.round(box.y),
    width: Math.round(box.width), height: Math.round(box.height), scale: 1,
  };

  const client = await ctx.newCDPSession(page);
  const play = await page.$('button[title="Play"]');
  if (play) await play.click();

  const t0 = Date.now();
  let i = 0;
  while (Date.now() - t0 < CAPTURE_MS) {
    const { data: b64 } = await client.send("Page.captureScreenshot", {
      format: "png", clip, fromSurface: true, captureBeyondViewport: false,
    });
    fs.writeFileSync(path.join(FRAMES_DIR, "f" + String(i).padStart(3, "0") + ".png"), Buffer.from(b64, "base64"));
    i++;
  }
  console.log(`captured ${i} frames -> ${FRAMES_DIR}`);
  await browser.close();
})().catch((err) => {
  console.error("render_escape_room.cjs failed:", err.message);
  process.exit(1);
});
