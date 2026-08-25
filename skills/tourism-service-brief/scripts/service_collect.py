"""관광 서비스 브리프의 재료를 모은다.

**지표 하나가 실패해도 멈추지 않는다.** 세 출처를 한 장에 모으는
리포트라, 소비자원 통계 하나가 늦게 발표됐다고 불편신고까지 못 보게
되면 리포트의 뜻이 없다. 실패는 삼키되 meta 에 사유를 남긴다 —
삼키고 남기지 않으면 빈 칸이 "값이 0"으로 읽힌다.
"""
import pathlib
import sys

# <skills>/<이름>/scripts/x.py 에서 parents[2] 가 skills 루트다.
# 소스 트리든 배포본이든 사용자 설치 위치든 이 깊이는 같다.
_SKILLS_ROOT = pathlib.Path(__file__).resolve().parents[2]
for _p in (_SKILLS_ROOT / "datalab-fetch" / "scripts",
           _SKILLS_ROOT / "tourism-service-brief" / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import client  # noqa: E402
import normalize  # noqa: E402
import period  # noqa: E402
import service_config as config  # noqa: E402

CATALOG_DIR = _SKILLS_ROOT / "datalab-fetch" / "catalog"
CATALOG_FILES = ("cpln_qid_catalog.yaml", "cnsel_qid_catalog.yaml",
                 "focus_qid_catalog.yaml")

_catalog = None


def load_catalog():
    """이 리포트가 쓰는 세 카탈로그를 합쳐 캐시한다.

    합치지 않으면 렌더가 지표 이름도 caution 도 붙이지 못한다.
    """
    global _catalog
    if _catalog is None:
        merged = {}
        for name in CATALOG_FILES:
            merged.update(normalize.load_catalog(CATALOG_DIR / name))
        _catalog = merged
    return _catalog


def _fetch_one(qid, ym1, ym2, *, extra=None, cache_dir=None,
               session_file=None, notes=None):
    """지표 하나. (DataFrame, 사유) 중 한쪽만 채워 돌려준다.

    부르기 전에 기간을 그 지표의 수록 시점까지 줄인다. 아직 발표되지
    않은 달은 오류가 아니라 빈 배열로 오기 때문이다.
    """
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


def collect(ym1, ym2, *, cache_dir=None, session_file=None):
    """({섹션: {제목: DataFrame}}, meta)."""
    sections = {}
    missing = {}
    missing_sections = []
    notes = {}
    catalog = load_catalog()

    for name, qids in config.SECTIONS.items():
        frames = {}
        for qid in qids:
            if qid == config.SENTIMENT_QID:
                # 한 qid 가 긍정·부정 두 표를 만든다. 파라미터로만
                # 갈리므로 여기서 두 번 부른다.
                for 라벨, 값 in config.SENTIMENT_KINDS:
                    frame, reason = _fetch_one(
                        qid, ym1, ym2, extra={"srchKwrdText": 값},
                        cache_dir=cache_dir, session_file=session_file,
                        notes=notes)
                    if reason is None:
                        frames[f"{catalog[qid]['name']} — {라벨}"] = frame
                    else:
                        missing[f"{qid}:{라벨}"] = reason
                continue
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

    # 감성 키워드 하나가 긍정·부정 두 표가 되므로 하나를 더한다.
    시도 = sum(len(q) for q in config.SECTIONS.values()) + 1
    수록 = 시도 - len(missing)
    meta = {
        "기준기간": f"{ym1}~{ym2}",
        "시도지표": 시도,
        "수록지표": 수록,
        "미수록": missing,
        "미수록섹션": missing_sections,
        "기간조정": notes,
        "세션상태": "만료" if "세션만료" in missing.values() else "정상",
    }
    return sections, meta
