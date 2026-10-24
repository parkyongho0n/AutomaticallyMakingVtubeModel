# Astra Studio 0.1

2D 캐릭터 제작 과정을 프로젝트 데이터와 빌드 파이프라인으로 분리한 **로컬 웹 제작 도구**입니다. 단순 이미지 자르기를 자동화하는 도구가 아닙니다. 완전한 독립 파츠(숨은 면·연결부 포함)를 생성하거나 등록하고, 배치·가림 관계를 편집한 뒤 PSD와 실제 Live2D 모델을 생성합니다.

현재 Linux + Python 3.11 이상을 지원합니다. Windows/macOS 네이티브 실행은 검증하지 않았습니다. Windows에서는 Linux 환경 또는 WSL을 사용하세요. 서버는 `127.0.0.1`에만 열리며 공개 호스팅 서비스가 아닙니다.

## 시작

저장소 루트에서:

```bash
python -m pip install -e .
python -m astra_studio serve --port 7860
```

브라우저에서 http://127.0.0.1:7860 을 여세요. **마녀 예제**는 `--repo`로 지정한 마녀 모델 저장소의 60개 파츠를 별도 프로젝트로 복사합니다. 기존 `output/` 모델은 수정하지 않습니다. 새 캐릭터는 **새 프로젝트 → 기준 이미지 등록 → 파츠 PNG 등록 또는 생성 → 배치·클리핑 조정 → 저장 → 빌드** 순서입니다.

`pip install .`로 설치한 패키지만 있을 때는 마녀 원본 자산과 전용 리깅 스크립트가 포함되지 않습니다. 예제는 [마녀 모델 저장소](https://github.com/parkyongho0n/astra-witch-vtuber/tree/build/astra-facial-tracking)를 별도로 체크아웃한 뒤 `--repo /path/to/astra-witch-vtuber`를 지정하세요.

## 빌드 도구 설정

PSD 조립에는 별도 SDK가 필요하지 않습니다. MOC3 생성에는 별도 설치한 PSD2Live가 필요합니다. 아래 경로는 설치 위치에 맞게 변경하세요.

```bash
export PSD2LIVE_BIN=/path/to/PSD2Live/bin/PSD2Live
export PSD2LIVE_SOURCE=/path/to/psd2live
export LIVE2D_BRIDGE=/path/to/liblive2d_renderer.so
export DISPLAY=:99
python -m astra_studio serve
```

- `PSD2LIVE_SOURCE`: `mcp_proxy.py`가 있는 폴더. Astra 전용 리그와 범용 눈썹 각도 보강에 사용합니다.
- `LIVE2D_BRIDGE`: 마녀 모델 저장소의 기존 네이티브 검증과 호환되는 Cubism Core/렌더 브리지. 파일 참조 검사와 별개로 실제 MOC3 일관성·파라미터 반응·메쉬를 검사합니다.
- `DISPLAY`: 사용 가능한 X11/Xvfb 디스플레이. 실제 렌더에는 OpenGL/셰이더 리소스도 필요합니다. 브리지 설치는 [기존 빌드 안내](BUILD.md)를 참고하세요.
- 도구·SDK 바이너리는 프로그램에 동봉하지 않으며 해당 라이선스가 적용됩니다.
- 설치 상태는 `python -m astra_studio doctor`로 확인합니다. 감지는 실행 성공을 보증하지 않으며 실패 이유는 작업 로그에 남습니다.

도구가 없으면 완료된 PSD/조립 이미지를 보존하고 필요한 설정을 표시합니다. 가짜 MOC3를 만들지 않습니다. 네이티브 브리지가 없을 때 ZIP을 만들더라도 준비도 문서에는 네이티브 검사를 생략했다고 기록됩니다.

## 이미지 생성

```bash
export OPENAI_API_KEY='your-key'
export ASTRA_IMAGE_MODEL=gpt-image-1
```

선택한 파츠의 **AI 파츠 생성**을 누르면 기준 이미지를 사용하는 이미지 편집 API에 한 파츠를 요청합니다. 요청 비용이 발생할 수 있습니다. 결과는 자동 덮어쓰기 없이 미리보기 후 **생성 파츠 적용**으로 적용합니다. 비밀 키는 프로젝트/ZIP에 저장하지 않습니다. 호환 제공자는 `ASTRA_IMAGE_BASE_URL`을 설정할 수 있습니다.

API가 없어도 **생성 프롬프트**를 내려받아 외부 이미지 도구에서 생성한 PNG를 등록할 수 있습니다. 생성 결과의 디자인 일치, 투명 배경, 숨은 면 완성도는 확인해야 합니다. 이 버전의 API 어댑터는 설정·오류 처리 경로를 제공하지만 실제 유료 생성 호출은 이번 검증에서 수행하지 않았습니다.

## 편집과 재현

- 목록 위쪽이 앞에 그려집니다. 드래그로 위치를, 우측 숫자로 크기를 편집합니다.
- 클리핑 대상은 아래쪽 비클리핑 파츠여야 합니다. 중첩 클리핑은 지원하지 않습니다.
- 편집용 `layers.psd`에는 클리핑을 픽셀에 반영합니다. 전체 원본 파츠는 `assets/`에 보존하고 런타임용 `model.psd`에는 전체 표면을 전달합니다. 런타임의 임의 클리핑 관계를 자동 이식하지는 않습니다. 리깅 도구의 눈 등 의미별 처리를 사용하므로 실제 렌더를 확인해야 합니다.
- **조립본 표시**와 **리깅 포함**은 별도입니다. 입 내부처럼 조립에서는 감추되 런타임에서 필요한 파츠를 포함할 수 있습니다.
- 저장은 새 버전을 만들고 충돌 시 덮어쓰지 않습니다. 버전 복원도 새 버전으로 남습니다.
- 프로젝트 ZIP은 원본 파츠와 설정을 포함합니다. **ZIP 열기**로 새 프로젝트에 복원합니다. 32MB 압축/160MB 확장 제한이 있습니다. 더 큰 프로젝트는 데이터 폴더를 직접 백업하세요.
- 빌드는 저장 시점의 독립 복사본으로 실행됩니다. 편집 중에도 결과가 섞이지 않습니다.
- 동일 입력의 완료 단계는 캐시를 재사용합니다. 위치 변경은 조립부터, 리그 설정 변경은 리깅부터 다시 실행합니다. 외부 도구 내부를 같은 경로로 교체한 뒤 강제 재빌드하려면 서버 종료 후 `studio_data/cache/`를 지우세요.
- 한 데이터 폴더에는 작업 관리자를 하나만 실행합니다. 웹 서버가 실행 중이면 CLI `build` 대신 웹 빌드를 사용하세요.

기본 데이터 폴더는 `studio_data/`이며 Git에서 제외됩니다. 다른 위치는 `--data /path`로 지정합니다. CLI 옵션은 하위 명령 앞에 씁니다.

```bash
python -m astra_studio --data studio_data import-astra
python -m astra_studio --data studio_data list
python -m astra_studio --data studio_data build PROJECT_ID --target package
```

## 프리셋과 한계

**범용 반신**은 파츠 별칭과 편집 가능한 초기 배치를 사용하는 자동 초안입니다. 초기 좌표는 원화 분석 결과가 아닙니다. 임의 캐릭터의 가려진 구조, 깊이, 얼굴 비율, 머리카락 가림을 완전 자동으로 이해하거나 방송 품질을 보장하지 않습니다. 고급 바스트 입체 리그도 범용 템플릿에서 자동 생성하지 않습니다.

**Astra**는 기존 마녀 모델의 정확한 별칭·파츠 구성과 전용 리깅 스크립트를 사용하는 고급 프리셋입니다. 다른 캐릭터에 그대로 적용하는 범용 리그가 아닙니다. 파츠 구조를 크게 바꾸면 전용 리그도 수정해야 합니다.

검증은 파일 참조, Core 일관성, 단일 축 극값 반응/뒤집힘, 12개 정지 렌더를 수행합니다. 미적 품질, 눈 가림, 복합 축 전체 공간, 물리 감쇠, 웹캠·VTube Studio 실사용을 통과했다고 주장하지 않습니다. 마지막 실제 모델 화면은 정지 렌더이며 실시간 추적 뷰어가 아닙니다.

## 개발 및 테스트

```bash
python -m pip install -e '.[test]'
python -m unittest discover -s tests -v
python -m playwright install chromium
python tests/browser_smoke.py
```

- `models.py`, `storage.py`: 데이터, 불변 이미지, 이력, ZIP 복원
- `art.py`: 합성, PSD, 재조립 오차
- `adapters.py`: 이미지 API, PSD2Live, Astra 전용 리그
- `jobs.py`, `worker.py`: 작업 격리, 취소, 캐시, 패키징
- `native.py`: 실제 Cubism 검사와 렌더
- `server.py`, `web/`: 로컬 API와 브라우저 편집기

실행 결과와 검증 범위는 [Studio 검증 기록](STUDIO_VALIDATION.md)을 참고하세요.
