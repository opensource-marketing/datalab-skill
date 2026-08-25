"""테마 지표를 섹션별로 인출한다.

지표 하나가 실패해도 나머지를 계속 모은다. 무엇이 왜 빠졌는지는 meta에
남겨 리포트에 그대로 싣는다.

# 모듈 이름에 theme_ 접두사를 붙인 이유: 다른 스킬도 collect.py를 가지고
# 있다. 한 프로세스에서 둘 다 쓰면 먼저 import된 쪽이 sys.modules를 차지한다.
"""
import pathlib
import sys

# <skills>/<이름>/scripts/x.py 에서 parents[2] 가 skills 루트다.
# 소스 트리든 배포본이든 사용자 설치 위치든 이 깊이는 같다.
_SKILLS_ROOT = pathlib.Path(__file__).resolve().parents[2]
for _p in (_SKILLS_ROOT / "datalab-fetch" / "scripts",
           _SKILLS_ROOT / "theme-market-brief" / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import client
import codes
import period
import normalize
import theme_config as config

_CATALOG_DIR = _SKILLS_ROOT / "datalab-fetch" / "catalog"
CATALOG_PATH = _CATALOG_DIR / "theme_qid_catalog.yaml"
# 크루즈는 방한여행 화면에 있어 테마 카탈로그가 아니라 별도 파일에
# 있다. 합쳐 읽지 않으면 테마 목록에는 보이는데 인출이 KeyError로
# 죽는다.
EXTRA_CATALOG_PATHS = (_CATALOG_DIR / "crus_qid_catalog.yaml",)
# 이 파라미터가 없으면 한류 경험률 지표가 빈 배열을 돌려준다.
KOR_WAVE_RESPONDENT = "vstkHopeDivNmChart01"
DEFAULT_RESPONDENT = "일반외국인"

_catalog_cache = None


def _label(theme):
    return config.THEMES[theme]["label"]


class CollectError(Exception):
    """수집을 시작할 수 없을 때. 사용자 입력이 원인이다."""


def load_catalog():
    global _catalog_cache
    if _catalog_cache is None:
        merged = dict(normalize.load_catalog(CATALOG_PATH))
        for path in EXTRA_CATALOG_PATHS:
            extra = normalize.load_catalog(path)
            # qid가 겹치면 어느 쪽이 이겼는지 알 수 없는 채로 리포트가
            # 나간다. 겹치지 않는 것을 여기서 못 박는다.
            clash = set(merged) & set(extra)
            if clash:
                raise CollectError(
                    f"카탈로그가 겹칩니다: {', '.join(sorted(clash))}")
            merged.update(extra)
        _catalog_cache = merged
    return _catalog_cache


def resolve_axis(theme, value):
    """테마의 축 값을 확인해 (파라미터dict, 표시이름)으로 만든다.

    테마가 축을 받지 않는데 값을 주면 거부한다. 조용히 무시하면 사용자는
    지역별 값을 봤다고 믿는다 — 의료관광은 실제로 그런 착각을 부른다.
    """
    axis = config.THEMES[theme]["axis"]
    if axis == config.AXIS_NONE:
        if value:
            raise CollectError(
                f"{_label(theme)}{codes.josa(_label(theme), '은', '는')} "
                f"전국 값만 제공합니다. "
                f"지역·국가를 지정할 수 없습니다: {value}")
        return {}, "전국"
    if not value:
        if axis == config.AXIS_COUNTRY_NAME:
            return {"NAT_CD": "글로벌"}, "글로벌"
        raise CollectError(
            f"{_label(theme)}{codes.josa(_label(theme), '은', '는')} "
            f"시도를 지정해야 합니다. "
            f"--sido 를 넣으세요.")
    if axis == config.AXIS_SIDO:
        hits = codes.resolve_sido(value)
        if not hits:
            raise CollectError(f"일치하는 시도가 없습니다: {value}")
        if len(hits) > 1:
            lines = "\n".join(f"  {c}  {n}" for c, n in hits)
            raise CollectError(f"'{value}'에 여러 시도가 일치합니다:\n{lines}")
        return {"SGG_CD": hits[0][0]}, hits[0][1]
    # 한류는 데이터랩이 한글 국가명을 그대로 받는다. 코드로 바꾸지 않는다.
    return {"NAT_CD": str(value).strip()}, str(value).strip()


def _period_params(qid, ym1, ym2):
    """카탈로그가 선언한 기간 파라미터 이름에 맞춰 값을 넣는다."""
    accepted = set(load_catalog()[qid].get("params") or ())
    if "BASE_YM1" in accepted:
        return {"BASE_YM1": str(ym1), "BASE_YM2": str(ym2)}
    return {}


def _fetch_one(qid, axis_params, ym1, ym2, cache_dir, session_file,
               notes=None):
    """지표 하나를 인출한다. (DataFrame, 사유) 중 한쪽만 채운다.

    부르기 전에 기간을 그 지표가 확인된 시점까지로 줄인다. 연 단위
    테마(한류)는 네 자리를 주고받으므로 손대지 않는다 — clamp 는 여섯
    자리 기준월만 다룬다.
    """
    catalog = load_catalog()
    if len(str(ym1)) == 6 and len(str(ym2)) == 6:
        used1, used2, note = period.clamp(qid, str(ym1), str(ym2))
        if note and notes is not None:
            notes[qid] = note
        if used2 is None:
            return None, "미발표"
        ym1, ym2 = used1, used2
    params = dict(axis_params)
    params.update(_period_params(qid, ym1, ym2))
    if KOR_WAVE_RESPONDENT in (catalog[qid].get("params") or ()):
        params.setdefault(KOR_WAVE_RESPONDENT, DEFAULT_RESPONDENT)
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


def collect(theme, *, axis_value=None, ym1=None, ym2=None, cache_dir=None,
            session_file=None):
    """한 테마의 모든 섹션 지표를 인출한다.

    반환값은 ({섹션명: {qid: DataFrame}}, meta)다.
    """
    if theme not in config.THEMES:
        raise CollectError(f"모르는 테마입니다: {theme}\n"
                           f"쓸 수 있는 테마: {', '.join(config.theme_names())}")
    axis_params, axis_label = resolve_axis(theme, axis_value)
    granularity = config.THEMES[theme]["period"]
    if ym1 is None or ym2 is None:
        ym1, ym2 = config.default_period(theme)

    sections = {}
    missing = {}
    notes = {}
    for name, qids in config.THEMES[theme]["sections"].items():
        frames = {}
        for qid in qids:
            frame, reason = _fetch_one(qid, axis_params, ym1, ym2,
                                       cache_dir, session_file, notes)
            if reason is None:
                frames[qid] = frame
            else:
                missing[qid] = reason
        if frames:
            sections[name] = frames

    attempted = len(config.qids_for(theme))
    meta = {
        "테마": theme,
        "테마명": config.THEMES[theme]["label"],
        "조회대상": axis_label,
        "기준기간": f"{ym1}~{ym2}",
        "기간단위": granularity,
        "기간조정": notes,
        "수록지표": attempted - len(missing),
        "시도지표": attempted,
        "미수록지표": missing,
        "세션상태": "만료" if "세션만료" in missing.values() else "정상",
    }
    return sections, meta
