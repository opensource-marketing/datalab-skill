"""해외 소셜 브리프의 재료를 모은다.

**지표 하나가 실패해도 멈추지 않는다.** 열 지표가 한 화면에서 오지만
탭이 둘이고 국가 파라미터 유무가 갈린다 — 한쪽이 늦게 발표됐다고
다른 쪽까지 못 보게 되면 리포트의 뜻이 없다. 실패는 삼키되 meta 에
사유를 남긴다. 삼키고 남기지 않으면 빈 칸이 "값이 0"으로 읽힌다.
"""
import pathlib
import sys

# <skills>/<이름>/scripts/x.py 에서 parents[2] 가 skills 루트다.
# 소스 트리든 배포본이든 사용자 설치 위치든 이 깊이는 같다.
_SKILLS_ROOT = pathlib.Path(__file__).resolve().parents[2]
for _p in (_SKILLS_ROOT / "datalab-fetch" / "scripts",
           _SKILLS_ROOT / "global-social-brief" / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import client  # noqa: E402
import normalize  # noqa: E402
import period  # noqa: E402
import social_config as config  # noqa: E402

CATALOG = _SKILLS_ROOT / "datalab-fetch" / "catalog" / "social_qid_catalog.yaml"
# 국가 이름 → 숫자 코드 표를 얻는 지표. 26개국을 NAT_CD 와 함께 준다.
COUNTRY_QID = "NAT_09_01_004"

_catalog = None


def load_catalog():
    global _catalog
    if _catalog is None:
        _catalog = normalize.load_catalog(CATALOG)
    return _catalog


def _fetch_one(qid, ym1, ym2, *, extra=None, cache_dir=None,
               session_file=None, notes=None):
    """지표 하나. (DataFrame, 사유) 중 한쪽만 채워 돌려준다."""
    catalog = load_catalog()
    쓸1, 쓸2, note = period.clamp(qid, ym1, ym2)
    if note and notes is not None:
        notes[qid] = note
    if 쓸2 is None:
        return None, "미발표"
    params = {"BASE_YM1": 쓸1, "BASE_YM2": 쓸2}
    params.update(extra or {})
    try:
        rows = normalize.fetch_qid(qid, params, catalog=catalog,
                                   cache_dir=cache_dir,
                                   session_file=session_file)
    except client.SessionExpired:
        return None, "세션만료"
    except client.FetchError:
        return None, "인출실패"
    if not rows:
        return None, "데이터없음"
    return normalize.to_frame(qid, rows, catalog=catalog), None


def country_codes(ym1, ym2, *, cache_dir=None, session_file=None):
    """({국가명: 숫자코드}, 사유). 성공하면 사유가 None.

    **이 화면의 국가 코드는 다른 지표와 체계가 다르다.** 다른 곳은
    `JP`·`CN` 두 글자인데 여기는 `392`·`156` 같은 ISO 숫자다.
    `codes.resolve_country()` 를 쓰면 빈 배열이 온다 — 그래서 표를
    코드에 박아 두지 않고 **응답에서 그때그때 읽는다.** 데이터랩이
    나라를 늘리면 그대로 따라간다.
    """
    frame, reason = _fetch_one(COUNTRY_QID, ym1, ym2, cache_dir=cache_dir,
                               session_file=session_file)
    if reason is not None:
        # **사유를 삼키면 원인을 감춘다.** 세션이 만료된 것과 그 나라
        # 이름을 못 알아본 것은 사용자가 할 일이 다르다.
        return {}, reason
    if "국가명" not in frame.columns or "국가코드" not in frame.columns:
        return {}, "코드표컬럼없음"
    return {str(n): str(c) for n, c in zip(frame["국가명"],
                                           frame["국가코드"])}, None


def resolve_country(name, table):
    """사람이 쓴 국가명을 (이름, 코드)로. 못 찾으면 (None, None).

    **틀린 코드에 오류가 오지 않는다** — 데이터랩은 모르는 `natCd`
    에 빈 배열을 준다. 부르기 전에 여기서 거른다.
    """
    text = str(name or "").strip()
    if not text:
        return None, None
    if text in table:
        return text, table[text]
    if text in table.values():
        for 이름, 코드 in table.items():
            if 코드 == text:
                return 이름, 코드
    부분 = [(n, c) for n, c in table.items() if text in n]
    if len(부분) == 1:
        return 부분[0]
    return None, None


def collect(ym1, ym2, *, country=None, cache_dir=None, session_file=None):
    """({섹션: {제목: DataFrame}}, meta)."""
    catalog = load_catalog()
    sections, missing, missing_sections, notes = {}, {}, [], {}

    for name, qids in config.GLOBAL_SECTIONS.items():
        frames = {}
        for qid in qids:
            frame, reason = _fetch_one(qid, ym1, ym2, cache_dir=cache_dir,
                                       session_file=session_file, notes=notes)
            if reason is None:
                frames[catalog[qid]["name"]] = frame
            else:
                missing[qid] = reason
        if frames:
            sections[name] = frames
        else:
            missing_sections.append(name)

    표, 표사유 = country_codes(ym1, ym2, cache_dir=cache_dir,
                              session_file=session_file)
    고른이름, 코드 = resolve_country(country or config.DEFAULT_COUNTRY, 표)
    if 코드 is None:
        # 나라를 못 고르면 국가별 섹션을 통째로 뺀다. 기본 코드로
        # 슬쩍 바꿔 부르면 사용자가 물은 나라의 표라고 읽는다.
        for name in config.COUNTRY_SECTIONS:
            missing_sections.append(name)
        for qids in config.COUNTRY_SECTIONS.values():
            for qid in qids:
                # 코드표를 아예 못 받았으면 그 사유를 그대로 쓴다.
                missing[qid] = 표사유 or "국가미해석"
    else:
        for name, qids in config.COUNTRY_SECTIONS.items():
            frames = {}
            for qid in qids:
                frame, reason = _fetch_one(
                    qid, ym1, ym2, extra={"natCd": 코드, "TAB_DIV": "2"},
                    cache_dir=cache_dir, session_file=session_file,
                    notes=notes)
                if reason is None:
                    frames[catalog[qid]["name"]] = frame
                else:
                    missing[qid] = reason
            if frames:
                sections[name] = frames
            else:
                missing_sections.append(name)

    시도 = (sum(len(q) for q in config.GLOBAL_SECTIONS.values())
            + sum(len(q) for q in config.COUNTRY_SECTIONS.values()))
    meta = {
        "기준기간": f"{ym1}~{ym2}",
        "국가": 고른이름,
        "국가코드": 코드,
        "고를수있는국가": sorted(표),
        "코드표사유": 표사유,
        "시도지표": 시도,
        "수록지표": 시도 - len(missing),
        "미수록": missing,
        "미수록섹션": missing_sections,
        "기간조정": notes,
        "세션상태": "만료" if "세션만료" in missing.values() else "정상",
    }
    return sections, meta
