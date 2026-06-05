// Render the semantic-toponav Foxglove replay into a PNG frame sequence by
// driving a *self-hosted, headless* open-source Foxglove (Lichtblick) with
// Playwright. The hosted app (app.foxglove.dev) requires sign-in and would
// upload the MCAP to a third party, so we point at a local Lichtblick instead
// (see build_hero_gif.sh, which starts the container and serves the MCAP).
//
// The replay is rendered from the committed MCAP only — no Python, no planner
// re-run here. Regenerate the MCAP first with examples/export_foxglove_mcap.py
// if the graph or route changes.
//
// Usage (normally invoked by build_hero_gif.sh):
//   node render.cjs <frames_dir> <base_url> <mcap_url>
//
// Requires: `npm install playwright` (or a global install resolvable by
// require) and a Chrome/Chromium channel available to Playwright.

const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const FRAMES_DIR = process.argv[2] || "/tmp/fxframes";
const BASE_URL = process.argv[3] || "http://localhost:8080";
const MCAP_URL = process.argv[4] || `${BASE_URL}/demo.mcap`;

// Playback speed < 1 means more captured frames per unit of robot motion, i.e.
// a smoother GIF (capture rate is bounded by headless GL readback, not by the
// player). CAPTURE_MS must cover the whole traverse: 8 s data / SPEED.
// Capture spans the whole traverse (8 s data / SPEED) so frames are evenly
// distributed regardless of the headless capture rate; SPEED is kept low enough
// that even a slow (~1.5 fps) capture still yields a smooth (~60+) frame count.
const SPEED = Number(process.env.SPEED || 0.12);
const CAPTURE_MS = Number(process.env.CAPTURE_MS || 70000);
const WIDTH = Number(process.env.WIDTH || 1600);
const HEIGHT = Number(process.env.HEIGHT || 900);

// Single 3D panel framed on the y=0 route plane (entrance -> elevator -> exec
// office), dark background, map as the fixed frame. targetOffset (not target)
// pans in follow-none mode; the TF connecting line is suppressed via
// scene.transforms.lineWidth = 0.
function heroLayout() {
  const panel = {
    layers: {
      grid1: {
        visible: true, frameLocked: true, label: "Grid", instanceId: "grid1",
        layerId: "foxglove.Grid", size: 14, divisions: 14, lineWidth: 0.5,
        color: "#0f2342", position: [6, 0, -0.08], rotation: [0, 0, 0], order: 1,
      },
    },
    cameraState: {
      distance: 15, perspective: true, phi: 70,
      target: [0, 0, 0], targetOffset: [6, 0, 2.6],
      targetOrientation: [0, 0, 0, 1], thetaOffset: 0, fovy: 45, near: 0.5, far: 5000,
    },
    followMode: "follow-none",
    followTf: "map",
    scene: { backgroundColor: "#060b1c", transforms: { showLabel: false, axisScale: 0, lineWidth: 0 } },
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
    configById: { "3D!hero": panel },
    globalVariables: {}, userNodes: {},
    playbackConfig: { speed: SPEED },
    layout: "3D!hero",
  };
}

// Lichtblick loads its *selected* layout from IndexedDB (lichtblick-layouts),
// not from the studio.layout localStorage cache, so we patch the record's
// baseline.data in place and clear the working copy.
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

  // First load establishes the origin + the default layout record we patch.
  await page.goto(BASE_URL + "/", { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForTimeout(5000);
  await injectLayout(page, heroLayout());

  // Reload with the data source so our patched layout drives the render.
  const url = `${BASE_URL}/?ds=remote-file&ds.url=${encodeURIComponent(MCAP_URL)}`;
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForTimeout(11000);

  const hide = await page.$('button[aria-label="Hide left sidebar"]');
  if (hide) await hide.click();
  // Hide the floating 3D interaction toolbar (pointer / 3D / ruler).
  await page.addStyleTag({ content: ".mui-1b64mk4-root{display:none !important;}" });
  await page.waitForTimeout(1200);

  const box = await (await page.$("canvas")).boundingBox();
  const clip = {
    x: Math.round(box.x), y: Math.round(box.y),
    width: Math.round(box.width), height: Math.round(box.height), scale: 1,
  };

  // CDP captureScreenshot is far faster than element.screenshot while the
  // WebGL scene is actively animating.
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
  const secs = (Date.now() - t0) / 1000;
  console.log(`captured ${i} frames in ${secs.toFixed(1)}s (${(i / secs).toFixed(1)} fps) -> ${FRAMES_DIR}`);

  await browser.close();
})().catch((err) => {
  console.error("render.cjs failed:", err.message);
  process.exit(1);
});
