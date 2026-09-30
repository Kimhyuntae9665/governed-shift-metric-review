# 현재 UI 화면과 영상 · 재현 기록

이 묶음은 P09 v2 화면 참조에 맞춰 개편한 P04를 실제 Linux Chrome에서 촬영했습니다. 합성 데이터와 저장된 CPU 계산만 사용했으며 **새 모델 호출은 0회**입니다. 캡처 전후의 원본 fixture, 계산 규칙, source hash, 권한 투영은 변경하지 않았습니다.

- 실행: `python3 scripts/refit_capture.py` (격리된 loopback `127.0.0.1:19104`)
- 브라우저: 설치된 Google Chrome, 데스크톱 1440×900 및 모바일 390×844
- 검사: 신규 화면 단언 14개; 기존 `scripts/refit_regression.py`의 11개 계산 사례·97개 브라우저 단언 별도 통과
- 이미지: Playwright가 실제 DOM과 페인트를 촬영한 PNG. 내용 수정·성공 합성 없음.
- 영상: Playwright가 실제 데스크톱 상호작용을 직접 기록한 WebM을 `ffmpeg`로 H.264 MP4 코덱 변환. 오버레이·합성 없음. 7.84초.
- 민감정보: 공개 데모 신원·가상 식별자만 표시. 새 GPU/Qwen 호출, 외부 서비스 전송 없음.

| 순서 | 기능·상태 | 파일 | SHA-256 |
|---:|---|---|---|
| 1 | 승인 지표·합산 분자와 분모·원본 행 | [01-combined-result.png](01-combined-result.png) | `e8920fa4af0c35cb791a159c583da7eb0203ee3ef4a44bb9bdfc71934eb50f47` |
| 2 | 채택 행과 원본 열람 | [02-accepted-sources.png](02-accepted-sources.png) | `7964cc2cbabe10753ad4429f0c8e025f7aefc264722809d03480facddabe81b4` |
| 3 | 원본 행·정확한 표시값·출처 해시 | [03-source-detail.png](03-source-detail.png) | `513a6499127cb3e85af361c4bda9c2e27359ce7ed16d68ee5ab43f676b83c0fe` |
| 4 | 23:30 기록 기준·정정 전 11/12 | [04-before-correction.png](04-before-correction.png) | `5d80a888e78ff6a31820b23fbd91bf732bdb5df64da58acbe37a11a655c35616` |
| 5 | 00:30 기록 기준·정정 후 147/160 | [05-after-correction.png](05-after-correction.png) | `72437afdb2244ee3733b70bae41e87bd9553c6f949213c60958d7f394145138e` |
| 6 | 이전 개정 제외와 정정 이력 | [06-superseded-row.png](06-superseded-row.png) | `d972cac3c5b5cd664bd856da616d7c4b1d87b5bc1dd048076656e6494603b2f7` |
| 7 | 동일 개정 충돌·격리·정의되지 않음 | [07-conflict-quarantine.png](07-conflict-quarantine.png) | `9f9465a01787cc6dd3b3680d1c25b607b76355210ed10e8bc2d305dc78351227` |
| 8 | 양품 누락·가동률과 미정의 OEE | [08-missing-good.png](08-missing-good.png) | `b8e7332f1fbf8743a5c5cf6195248f66582337f94cbbd3831ac5f68eb540b3c2` |
| 9 | 산술 영수증 검토 기록·이력 | [09-review-history.png](09-review-history.png) | `7de5758ef4c7b19228c136bb38333ae10eb8d21fb14a3400d36d1534ba6341bf` |
| 10 | 390px 화면·선택과 결과 | [10-mobile-390.png](10-mobile-390.png) | `fcb4f731ed39f419783836b1096d119a2ebedc1682a3770ddb99d0b68b3fcdb2` |

영상: [workflow.mp4](workflow.mp4) · SHA-256 `23b95f0c76b539cd3724b011363d14a5ed0d0ff115bb14434803dfb169793189`.

기존 `docs/demo/`의 다른 PNG/영상은 이전 UI에서 촬영한 **역사적 데모**입니다. 모델 실행 장면은 이 현재 CPU 화면 묶음에 포함하지 않았고, 과거 저장된 모델 결과나 평가를 다시 생성하지 않았습니다.
