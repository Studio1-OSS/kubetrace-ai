# Launch video

A 45-second, 1080p30 launch video built from one real live run (Beam, `reflection/beam`, run `20261016-191342-7e275b`). Every line, number and diff in it comes from that run.

- `index.html` is the scene graph. Every frame is a pure function of time (`window.render(t)`).
- `render.mjs` renders the frames with Playwright: `node render.mjs`, or `node render.mjs preview 12 30` for single stills.
- `music.py` synthesizes the original soundtrack (no samples): `python music.py music.wav` (needs numpy).
- `assets/clips/` holds the real-UI footage cut from the demo recording (not committed). Recreate it with the `ffmpeg -ss … -t …` cuts in the commit history, from `apps/web/demo-output/…/video.webm`, produced by `npx playwright test --config playwright.demo.config.ts`.

Encode:

```bash
ffmpeg -framerate 30 -i frames/%05d.jpg -i music.wav -filter_complex "[1:a]loudnorm=I=-14:TP=-3:LRA=11,alimiter=limit=0.63:level=disabled:attack=0.5:release=40,aresample=48000[a]" \
  -map 0:v -map "[a]" -c:v libx264 -preset slow -crf 17 -pix_fmt yuv420p -c:a aac -b:a 256k -movflags +faststart -shortest kubetrace-ai-launch.mp4
```

The Nebius Token Factory logo is the provider's mark, used to credit inference.

The limiter is there because AAC encoding adds about 1.5 dB of overshoot on this soundtrack's sharp synthesized transients, so `loudnorm` alone (single pass, `TP=-1`) measured +0.2 dBTP after encoding. With it the master measures -14.6 LUFS integrated and -1.7 dBTP (`ffmpeg -i kubetrace-ai-launch.mp4 -af ebur128=peak=true -f null -`).
