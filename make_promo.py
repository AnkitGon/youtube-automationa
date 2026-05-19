"""
Frame-by-frame capture of promo.html via Playwright -> mp4.
Output: promo_silent.mp4 (no audio, fed to add_sfx.py later)
"""
import asyncio, os, shutil, subprocess, time
from pathlib import Path
from playwright.async_api import async_playwright

FPS       = 60
DURATION  = 40.0
TOTAL     = int(FPS * DURATION)
W, H      = 1920, 1080
HERE      = Path(__file__).parent
FRAMES    = HERE / "frames"
HTML      = HERE / "promo.html"
OUT       = HERE / "promo_silent.mp4"


async def render():
    if FRAMES.exists():
        shutil.rmtree(FRAMES)
    FRAMES.mkdir(parents=True)

    print(f"Launching Chromium...")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(
            viewport={"width": W, "height": H},
            device_scale_factor=1,
        )
        page = await ctx.new_page()
        await page.goto(f"file:///{HTML.as_posix()}")
        # wait for fonts
        await page.wait_for_function("window.READY === true", timeout=30000)
        # warm-up
        await page.evaluate("window.setTime(0)")
        await asyncio.sleep(0.5)

        t0 = time.time()
        last_report = t0
        for i in range(TOTAL):
            t = i / FPS
            await page.evaluate(f"window.setTime({t})")
            # tiny pause lets any pending layout flush
            await page.screenshot(
                path=str(FRAMES / f"f_{i:05d}.png"),
                animations="disabled",
                full_page=False,
            )
            now = time.time()
            if now - last_report > 2.0:
                pct = (i + 1) / TOTAL * 100
                elapsed = now - t0
                eta = elapsed / (i + 1) * (TOTAL - i - 1)
                print(f"  frame {i+1:4d}/{TOTAL}  ({pct:5.1f}%)  "
                      f"elapsed {elapsed:5.1f}s  ETA {eta:5.1f}s")
                last_report = now

        await browser.close()

    print(f"\nAll {TOTAL} frames captured in {time.time() - t0:.1f}s.")
    print("Encoding with ffmpeg...")

    subprocess.run([
        "ffmpeg", "-y",
        "-framerate", str(FPS),
        "-i", str(FRAMES / "f_%05d.png"),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-crf", "16",
        "-preset", "slow",
        "-movflags", "+faststart",
        str(OUT),
    ], check=True)

    print(f"\n-> {OUT}")
    # cleanup frames
    shutil.rmtree(FRAMES)
    print("(cleaned up frames/)")


if __name__ == "__main__":
    asyncio.run(render())
