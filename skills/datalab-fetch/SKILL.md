---
name: datalab-fetch
description: 한국관광 데이터랩(datalab.visitkorea.or.kr)에서 관광 데이터를 인출한다. 방한 외래관광객, 국가별 방한객수, 항공 좌석 공급, 외래관광객 지출·재방문 등 데이터랩 지표가 필요할 때 사용한다. 다른 Skill이 데이터 원천으로 호출하는 기반 계층이다.
---

`{SKILLS_DIR}` = 이 스킬들이 설치된 디렉토리(이 스킬 폴더의 부모). 소스
저장소와 배포본에서 실제 설치 위치가 다르므로, 아래 명령을 그대로 쓰기
전에 이 값을 자신의 설치 경로로 바꿔라.

# 데이터랩 데이터 인출

## 동작 방식

데이터랩의 모든 화면은 단일 API 위에 있다. qid로 지표를 지정한다.

```
POST https://datalab.visitkorea.or.kr/visualize/getTempleteData.do
  qid=NAT_08_01_021&natCd=999&BASE_YM1=202501&BASE_YM2=202512&srchAreaDate=1
→ {"list":[{...}, ...]}
```

`catalog/qid_catalog.yaml`이 qid별 이름·필수 파라미터·인증 등급·컬럼 의미를 담고 있다.
**qid를 직접 추측하지 말고 반드시 카탈로그를 먼저 읽어라.**

## 카탈로그 세 개의 역할이 다르다

| 파일 | 성격 | 영역 | 조회 축 |
|---|---|---|---|
| `catalog/qid_catalog.yaml` | **검증됨** | 인바운드 `NAT_*` | 국가(`natCd`) |
| `catalog/loc_qid_catalog.yaml` | **검증됨** | 지역 `LN_*` | 시군구 5자리 |
| `catalog/bzm_qid_catalog.yaml` | **검증됨** | 관광사업체 `BZM_*` | 시군구 5자리 |
| `catalog/theme_qid_catalog.yaml` | **검증됨** | 테마 `BY_TH_*` | 시도 2자리 / 없음 |
| `catalog/poi_qid_catalog.yaml` | **검증됨** | 관광지 `LN_05_*` | `CONT_ID` |
| `catalog/outbound_qid_catalog.yaml` | **검증됨** | 아웃바운드 `NAT_05_*` | 없음(전국) |
| `catalog/qid_index.yaml` | **미검증 색인** | 데이터랩 전 화면 660여 개 | — |

관광지 코드는 고정 표가 없다. `scripts/poi.py`로 지역을 좁혀 찾는다.
해양관광은 배열 파라미터가 필요하다. `scripts/marine.py`가 만들어 준다.

**조회 축을 틀리면 오류가 아니라 빈 배열이 온다.** 같은 `SGG_CD` 자리에
시군구 다섯 자리를 받는 지표와 시도 두 자리를 받는 지표가 섞여 있다.
테마 카탈로그는 항목마다 `axis` 필드로 축을 못 박아 둔다.

검증된 카탈로그는 실제 호출로 응답을 확인하고 컬럼 의미까지 적어 둔 것이다.
색인은 사이트 화면 JS에서 이름과 파라미터를 긁어낸 목록일 뿐이다 — 값이 정말
나오는지, 컬럼이 무엇을 뜻하는지 확인하지 않았다. **색인의 qid를 확인 없이
리포트에 쓰지 마라.**

`load_catalog()`는 인자가 없으면 인바운드 카탈로그를 돌려준다. 지역 지표를 쓸 때는
경로를 반드시 명시하고, 그 카탈로그 객체를 `fetch_qid(..., catalog=cat)`와
`to_frame(..., catalog=cat)` 양쪽에 넘겨라.

지역 지표는 `natCd` 대신 `SGG_CD`(시군구 5자리)를 쓰고, `dispYn=Y`가 없으면
값이 비어 있는 껍데기 레코드가 온다(카탈로그의 `fixed_params`가 자동 처리한다).

## 사용법

```python
import sys
sys.path.insert(0, "{SKILLS_DIR}/datalab-fetch/scripts")
import workspace
from normalize import fetch_qid, to_frame

rows = fetch_qid("NAT_08_01_021",
                 {"natCd": "999", "BASE_YM1": "202501", "BASE_YM2": "202512"},
                 cache_dir=str(workspace.cache_dir()),
                 session_file=str(workspace.session_file()))
df = to_frame("NAT_08_01_021", rows)   # 컬럼명이 한글 라벨로 바뀐다
```

캐시·세션 경로를 문자열로 박지 마라 — `cache_dir="data/raw"`처럼 쓰면
현재 디렉토리 바로 밑에 `data/raw/`가 생긴다. `workspace.cache_dir()`가
가리키는 작업 공간(기본 `.datalab/data/raw/`)과 어긋나는 별도의
디렉토리다.

`fetch_qid`가 카탈로그의 `fixed_params`를 자동으로 병합하므로 직접 넣지 않는다.
카탈로그에 없는 컬럼이 응답에 섞여 있으면 `to_frame`이 경고를 찍고 원본 컬럼명을
그대로 남긴다 — 카탈로그 갱신 신호이니 무시하지 마라.

## 인증

qid마다 인증 요구가 다르다. 카탈로그의 `auth` 필드를 본다.

- `public` — 쿠키 없이 동작
- `session` — 로그인 세션 필요. 없으면 **HTTP 200에 빈 배열**이 온다

세 번째 실패 모드가 있다: **HTTP 200에 0바이트 본문.** 빈 배열과 다르다.
`client.py`가 이를 JSON 파싱 실패로 만나 `FetchError`를 던지므로 빈 배열과
자동으로 구분된다. 서버가 해당 지표를 더 이상 제공하지 않을 때 나타난다
(지역 영역의 **시군구 단위** 내국인 카드소비 계열 8개가 이 상태다. 다만 시도 단위 내국인 관광소비는 야간관광 지표에 남아 있다).

**`auth: session` qid의 빈 배열은 그 자체만으로 세션 만료를 의미하지 않는다.**
외래관광객조사류 qid(예: `NAT_07_01_018`)는 조사 대상국이 약 20개국뿐이라,
조사 대상이 아닌 나라를 조회하면 세션이 멀쩡해도 빈 배열이 온다. 이를
"세션 만료"로 오판해 조사 비대상국 데이터를 지워버린 실제 사고가 있었다.

그래서 `client.py`는 `auth: session` 조회가 빈 배열을 받으면 곧바로 예외를
던지지 않고, 중국(CN)을 기준국으로 한 캐노니컬 프로브를 10분당 최대
한 번만 수행해 세션 자체가 유효한지 먼저 확인한다. 프로브가 값을 반환하면
세션은 유효한 것이고, 원래의 빈 배열은 "그 나라는 조사 대상이 아님"이라는
정상적인 결과이므로 그대로 빈 리스트가 반환된다. 프로브마저 빈 배열이면
그때 비로소 `client.SessionExpired`가 발생한다.

**이 Skill은 로그인을 다루지 않는다.** `SessionExpired`가 나면 `datalab-auth`
Skill로 넘겨라. `workspace.session_file()`(기본
`.datalab/.auth/storage_state.json`)이 두 Skill의 유일한 계약이다.

## 주의

- 호출 간 0.5초 간격이 클라이언트에 내장되어 있다. 우회하지 마라.
- 응답은 `workspace.cache_dir()`(기본 `.datalab/data/raw/`)에 캐시된다.
  같은 조건의 재조회는 네트워크를 타지 않는다.
- 결과물을 외부에 배포할 때는 출처를 명시한다:
  `출처: 한국관광공사 한국관광 데이터랩(datalab.visitkorea.or.kr)`
- 카탈로그에 없는 지표가 필요하면 아래 "새 지표 찾기"를 따르라. 추측하지 마라.


## 새 지표 찾기

카탈로그에 없는 지표가 필요할 때의 순서다. 어느 단계도 건너뛰지 마라 —
이름만 보고 지표를 고르면 엉뚱한 값을 리포트에 싣게 된다.

### 1. 색인에서 찾는다

```bash
python3 {SKILLS_DIR}/datalab-fetch/scripts/index.py search 숙박 사업체
python3 {SKILLS_DIR}/datalab-fetch/scripts/index.py show BZM_03_01_002
```

결과의 `[검증됨:...]` 표시가 있으면 그대로 쓰면 된다. `[미검증]`이면 
소스 저장소에서 추가 검증 단계를 거친다.
`[미검증·주석]`은 화면 JS에서 주석 처리된 호출이다 — 서버는 여전히 응답할 수
있지만 사이트가 화면에 그리지 않는 지표이므로 특히 조심해서 사용하라.

### 2. 새 지표를 검증한다

새 지표를 실제로 불러 보고 파라미터를 확인하는 작업은 소스 저장소의
`references/개발자-검사도구.md` 에 "새 지표 탐사" 섹션으로 적혀 있다.
호출 명령과 응답 값의 뜻, 파라미터 캡처 방법이 그 안에 있다.

검증이 끝나면 컬럼 라벨은 **사이트가 쓰는 이름을 그대로** 쓴다. 라벨을 지어내지 마라 —
`NAT_08_01_007`을 "방문목적"으로 오해해 리포트에 잘못 실은 사고가 있었다.

## 색인의 한계

- 색인 헤더에 적힌 화면들은 주소로 열면 **본문 없는 껍데기 문서**가 온다.
  오류가 아니라 정상 응답이라서 "지표 0개"처럼 보이지만 사실은 읽지 못한
  것이다. 그 화면의 지표는 색인에 없다.
- 색인의 파라미터 목록에는 화면 렌더링용 변수가 섞일 수 있다.
- 한 qid에 이름이 여러 개 붙어 있을 수 있다. 화면마다 다르게 부르기 때문이다.
