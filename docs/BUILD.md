> 이 문서는 [마녀 모델 저장소](https://github.com/parkyongho0n/astra-witch-vtuber/tree/build/astra-facial-tracking)의 기존 빌드 환경 참고 자료입니다. 아래 scripts/ 및 output/ 경로는 해당 저장소 기준입니다. 이 프로그램의 실행 절차는 [STUDIO.md](STUDIO.md)를 따르세요.

# Build and validation

Python 3.12, JDK bundled with PSD2Live 3.5.1 Linux x64. Install `requirements.txt` in a virtual environment.

1. `python scripts/build_layers.py` assembles the checked-in complete generated parts; writes canonical PSD, intermediate semantic-alias PSD, PNG parts and assembly verification.
2. Obtain [PSD2Live v3.5.1](https://github.com/tsunehimatoi/psd2live/releases/tag/v3.5.1) and its source. Set `PSD2LIVE_BIN` to its launcher and `PSD2LIVE_SOURCE` to its source directory (containing `mcp_proxy.py`). Start a fresh `PSD2Live mcp` service; set its local endpoint and token with `PSD2LIVE_MCP_ENDPOINT` and `PSD2LIVE_MCP_TOKEN`. Keep the token local.
3. `python scripts/build_runtime.py` generates the rig, imports its CMO3, adds brow angles/accessory physics/closed-mouth forms, saves an editable history archive, exports and registers six expressions.
4. Set `LIVE2D_BRIDGE` to your locally obtained PSD2Live/Cubism native bridge. Native bridge shaders must be beside it in `FrameworkShaders`. A working X11/GLX context is needed for rendering (Xvfb with Mesa works).
5. `python scripts/validate_bundle.py` checks MOC consistency and actual per-parameter geometry/opacity response.
6. `DISPLAY=:99 python scripts/render_runtime.py` renders actual final MOC3 test poses, full images, face crops and the contact sheet.
7. `DISPLAY=:99 python scripts/check_physics.py` measures a six-second native physics response.

No generator or SDK binary is vendored. Consult the upstream and Live2D licenses before distributing those tools. Generated artwork and model assets are distinct from third-party tool binaries.

Release archive verified SHA-256: `2450a06bc2c2397899036900729be5766fde43e9d1f7f04bdfb21b3b9d6dff2e` (PSD2Live-3.5.1-linux-x64.tar.gz). Native validation reported Cubism Core 6.0.1; target file is Cubism 5.0 MOC version 5. Older VTube Studio/Core support is not certified.

The 100+ MB `output/editor/witch.psd2live` history archive, redundant alias PSD and intermediate atlas are ignored by Git. The final PSD, CMO3, runtime textures and MOC3 are tracked. The saved reference is the deterministic starting point; rerunning image generation is not deterministic.

## Current revision

`assets/derived/complete_parts/` contains eight active generated sheets of complete isolated objects. `scripts/build_layers.py` unpacks their disconnected objects, preserves full surfaces, and positions them with explicit attachment bounds. `scripts/facial_art.py` paints full ocular/oral parts without sampling the assembled reference. The generated artwork is saved; rerunning image generation is not deterministic.

The dedicated MCP workspace is replaced by the build (`mode=new, discard_unsaved=True`). Do not point it at unrelated unsaved work. Use normalized object coordinates for deformation operations. After export, run `finalize_bundle.py` to register expressions and remove disabled iris-jelly physics.

Run `DISPLAY=:99 python scripts/validate_all.py`, then `python scripts/package_model.py`. Validation needs the native bridge and `FrameworkShaders`, a working X11/GLX context (Xvfb works), and ffmpeg/libx264. The runtime ZIP is written next to the repository. `complete_parts_provenance.json` records source-sheet hashes and placement; `attachment_contract.json` records ownership and occlusion surfaces.

The older derived underpaint images remain as historical files but are not used by the current artwork build. Current PSD/MOC counts and hashes are collected by `summarize_validation.py`, not manually maintained.
