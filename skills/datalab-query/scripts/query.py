"""데이터랩 지표 하나를 임의 조건으로 조회해 표로 내놓는 CLI.

리포트 Skill들은 미리 정한 질문에만 답한다. 이 스크립트는 사용자가
그때그때 던지는 질문에 답하기 위한 것이다 — 지표 하나, 조건 하나,
표 하나.

**검증된 카탈로그와 미검증 색인을 섞지 않는다.** 카탈로그에 있는 qid는
컬럼이 한글 라벨로 바뀌어 나오고, 색인에만 있는 qid는 원본 컬럼명 그대로
나오면서 머리말에 미검증 경고가 붙는다. 이름이 그럴듯하다고 값의 의미까지
아는 것은 아니다.
"""
import argparse
import pathlib
import sys

import pandas as pd

# <skills>/<이름>/scripts/x.py 에서 parents[2] 가 skills 루트다.
# 소스 트리든 배포본이든 사용자 설치 위치든 이 깊이는 같다.
_SKILLS_ROOT = pathlib.Path(__file__).resolve().parents[2]
for _p in (_SKILLS_ROOT / "datalab-fetch" / "scripts",
           _SKILLS_ROOT / "datalab-query" / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import client
import codes
import index as qid_index
import marine
import normalize
import period
import poi
import table
import workspace  # noqa: E402

CACHE_DIR = workspace.cache_dir()
SESSION_FILE = workspace.session_file()
LOGIN_HINT = "python3 " + workspace.display_path(
    _SKILLS_ROOT, "datalab-auth", "login.py")
TARGET_COLUMN = "조회대상"
DEFAULT_LIMIT = 30

# 검증된 카탈로그 목록은 index.py가 유일한 출처다. 여기 따로 적어 두면
# 카탈로그를 늘릴 때 한쪽만 고치게 되고, 그러면 새 지표가 조용히
# "미검증"으로 표시된다(실제로 아웃바운드 카탈로그에서 그랬다).
CATALOG_FILES = qid_index.CURATED_PATHS

# 기간 파라미터는 지표마다 이름이 다르다. 지표가 실제로 받는 이름을 보고
# 고른다 — 축제 계열은 연 단위(BASE_YY1)라 월을 넣으면 빈 배열이 온다.
_PERIOD_FORMS = [
    (("BASE_YM1", "BASE_YM2"), lambda ym: ym),
    (("BASE_YY1", "BASE_YY2"), lambda ym: ym[:4]),
    (("bgngYm", "endYm"), lambda ym: ym),
    # 인기 관광지(내비게이션 검색) 계열만 이 이름을 쓴다. 모르면
    # BASE_YM1을 보내게 되고, 오류가 아니라 빈 배열이 온다.
    (("BASE_YM_TMAP_FR", "BASE_YM_TMAP_TO"), lambda ym: ym),
]
_REGION_KEYS = ("SGG_CD", "SIDO_CD")
_COUNTRY_KEYS = ("natCd", "NAT_CD")
# 시도 축 지표(야간관광 등)는 SGG_CD 자리에 시도 두 자리를 넣는다.
# 시군구 다섯 자리를 넣으면 오류가 아니라 빈 배열이 와서 원인을 놓치기 쉽다.
_SIDO_KEYS = ("SGG_CD", "SIDO_CD")
_POI_KEYS = ("CONT_ID",)
# 비교 화면은 축 코드를 이 이름들로도 함께 받는다. 하나라도 빠지면
# 데이터랩이 JSON이 아니라 0바이트 본문을 준다.
_MIRROR_KEYS = ("arrSggCd[]", "CMPN_SGG_CD")
_FESTIVAL_KEYS = ("FSTV_ID",)
# --attraction 은 "지역:이름" 형식이다. 관광지 이름은 전국에서 유일하지
# 않아서("중앙시장"은 여러 지역에 있다) 지역을 함께 받아야 한다.
ATTRACTION_SEP = ":"


class QueryError(Exception):
    """조회를 시작할 수 없을 때. 사용자 입력이 원인이다."""


def find_qid(qid):
    """qid가 어디에 있는지 찾는다. (출처, 항목)을 돌려준다.

    출처는 카탈로그 이름이거나 "색인"이거나 None(어디에도 없음)이다.
    카탈로그를 먼저 본다 — 같은 qid가 양쪽에 있으면 검증된 쪽이 옳다.
    """
    for label, path in CATALOG_FILES.items():
        catalog = normalize.load_catalog(path)
        if qid in catalog:
            return label, catalog
    entry = qid_index.describe(qid)
    if entry is not None:
        return "색인", entry
    return None, None


def known_params(source, holder, qid):
    """그 qid가 받는다고 알려진 파라미터 이름들."""
    if source == "색인":
        return set(holder.get("params") or ())
    if source is None:
        return set()
    entry = holder[qid]
    return set(entry.get("params") or ()) | set(entry.get("fixed_params") or {})


def period_params(known, ym1, ym2, granularity=None):
    """--from/--to를 그 지표가 쓰는 기간 파라미터 이름으로 옮긴다.

    이름만 보고 자릿수를 정하면 안 된다. 한류 계열은 파라미터 이름이
    BASE_YM1인데도 연 단위라 네 자리를 받는다 — 여섯 자리를 넣으면
    오류가 아니라 빈 배열이 오고, 사용자는 그 해에 조사가 없었다고 읽는다.
    """
    if ym1 is None and ym2 is None:
        return {}
    if granularity == "year":
        out = {}
        keys = next((k for k, _ in _PERIOD_FORMS if k[0] in known),
                    ("BASE_YM1", "BASE_YM2"))
        if ym1 is not None:
            out[keys[0]] = str(ym1)[:4]
        if ym2 is not None:
            out[keys[1]] = str(ym2)[:4]
        return out
    for keys, convert in _PERIOD_FORMS:
        if keys[0] in known:
            out = {}
            if ym1 is not None:
                out[keys[0]] = convert(ym1)
            if ym2 is not None:
                out[keys[1]] = convert(ym2)
            return out
    # 알려진 이름이 없으면 가장 흔한 형태로 보낸다. 틀리면 빈 배열이
    # 오고, 그때는 --param 으로 직접 지정하라고 안내한다.
    out = {}
    if ym1 is not None:
        out["BASE_YM1"] = ym1
    if ym2 is not None:
        out["BASE_YM2"] = ym2
    return out


def _axis_key(known, candidates, fallback):
    for key in candidates:
        if key in known:
            return key
    return fallback


def resolve_attractions(values, *, cache_dir=None, session_file=None):
    """--attraction 값("지역:이름")을 (CONT_ID, 표시이름)으로 바꾼다."""
    targets = []
    for value in values or ():
        if ATTRACTION_SEP not in value:
            raise QueryError(
                f"--attraction 은 '지역{ATTRACTION_SEP}이름' 형식입니다: {value}\n"
                f"  예: --attraction '강릉시{ATTRACTION_SEP}경포해수욕장'")
        region, name = value.split(ATTRACTION_SEP, 1)
        try:
            cont_id, found = poi.resolve_one(
                name.strip(), region.strip(),
                cache_dir=cache_dir, session_file=session_file)
        except poi.PoiError as exc:
            raise QueryError(str(exc)) from exc
        targets.append(("관광지", cont_id, found))
    return targets


def _reject_region_on_sido_axis(qid, source, holder, targets):
    """시도 축 지표에 시군구를 넣었으면 부르기 전에 멈춘다.

    대부분의 시도 축 지표는 다섯 자리를 받으면 빈 배열을 준다. 그건
    사용자도 이상한 줄 안다. 문제는 BDT_01_01_003_4처럼 **다섯 자리를
    조용히 버리고 전국 시도표를 돌려주는** 지표다 — 그럴듯한 숫자가
    나오므로 사용자는 그것을 자기 시군구 값으로 읽고 리포트에 싣는다.
    빈 표보다 나쁜 실패다.
    """
    if source == "색인":
        return
    if (holder.get(qid) or {}).get("query_axis") != "시도":
        return
    bad = [name for kind, _, name in targets if kind == "지역"]
    if not bad:
        return
    raise QueryError(
        f"{qid}는 시도 축 지표입니다. 시군구({', '.join(bad)})를 넣으면 "
        f"값이 무시되거나 전국 표가 옵니다.\n"
        f"  --sido <시도명> 으로 다시 실행하세요.")


def resolve_targets(regions, countries, sidos=(), festivals=()):
    """--region/--sido/--country/--festival 값을 (코드, 표시이름)으로 바꾼다.

    하나의 값이 여러 곳에 걸리면 예외를 던진다. 임의로 하나를 고르면
    사용자는 자기가 묻지 않은 지역의 숫자를 보게 된다.
    """
    targets = []
    for kind, values, resolver in (("지역", regions, codes.resolve_region),
                                   ("시도", sidos, codes.resolve_sido),
                                   ("국가", countries, codes.resolve_country),
                                   ("축제", festivals, codes.resolve_festival)):
        for value in values or ():
            hits = resolver(value)
            if not hits:
                # 세종은 시군구 271곳에 없고 시도로만 있다. 없는 이름과
                # 축이 다른 지역을 구분하지 않으면 사용자는 표기를 고쳐
                # 가며 헛돈다.
                extra = codes.sido_hint(value) if kind == "지역" else None
                # 축제는 여든여섯 개다. "없습니다"만 내면 무엇으로 고쳐
                # 써야 할지 알 수 없다 — 겹치는 낱말이 많은 것을 알려 준다.
                if kind == "축제":
                    가까운 = codes.nearest_festivals(value)
                    if 가까운:
                        목록 = "\n".join(f"  {c}  {n}" for c, n in 가까운)
                        extra = f"이런 이름이 있습니다:\n{목록}"
                    else:
                        # 겹치는 이름조차 없으면 표기 문제가 아니라
                        # **목록에 없는 축제**다. 그 말을 하지 않으면
                        # 사용자는 "강릉단오제"를 여러 표기로 바꿔 가며
                        # 헛돈다 — 데이터랩은 문화관광축제로 지정된
                        # 것만 다룬다.
                        n = len(codes.load_festival_codes())
                        extra = (f"데이터랩은 문화관광축제로 지정된 "
                                 f"{n}곳만 다룹니다. 전체 목록:\n"
                                 f"  python3 "
                                 f"{workspace.display_path(_SKILLS_ROOT, 'datalab-fetch', 'codes.py')} "
                                 f"festival")
                raise QueryError(
                    f"일치하는 {kind}{codes.josa(kind, '이', '가')} "
                    f"없습니다: {value}" + (f"\n{extra}" if extra else ""))
            if len(hits) > 1:
                lines = "\n".join(f"  {c}  {n}" for c, n in hits)
                raise QueryError(
                    f"'{value}'에 여러 {kind}{codes.josa(kind, '이', '가')} "
                    f"일치합니다. "
                    f"하나를 골라 다시 실행하세요:\n{lines}")
            targets.append((kind, *hits[0]))
    return targets


def fetch_one(qid, source, holder, params, *, cache_dir=None,
              session_file=None):
    """한 조건으로 한 번 인출하고 DataFrame으로 만든다."""
    if source in CATALOG_FILES:
        rows = normalize.fetch_qid(qid, params, catalog=holder,
                                   cache_dir=cache_dir,
                                   session_file=session_file)
        return normalize.to_frame(qid, rows, catalog=holder)

    # 색인에만 있는 qid는 인증 등급을 모른다. auth="public"으로 부른다 —
    # "session"으로 부르면 client가 세션 확인을 위해 중국(CN) 프로브를
    # 끼워 넣는데, 국가 축이 아닌 지표에는 그 프로브가 무의미하다.
    # 쿠키 자체는 auth와 무관하게 전송되므로 로그인 지표도 값이 나온다.
    rows = client.fetch(qid, params, auth="public", cache_dir=cache_dir,
                        session_file=session_file)
    return pd.DataFrame(rows)


def run(qid, *, regions=(), countries=(), sidos=(), attractions=(),
        festivals=(), marine_region=None,
        ym1=None, ym2=None, extra=None, cache_dir=None, session_file=None):
    """조회를 실행해 (DataFrame, 메타) 를 돌려준다."""
    source, holder = find_qid(qid)
    if source is None:
        raise QueryError(
            f"색인에도 카탈로그에도 없는 qid입니다: {qid}\n"
            f"  python3 "
            f"{workspace.display_path(_SKILLS_ROOT, 'datalab-fetch', 'index.py')} "
            f"search <낱말> 로 먼저 찾으세요.")

    known = known_params(source, holder, qid)
    granularity = (None if source == "색인"
                   else (holder.get(qid) or {}).get("granularity"))
    base = period_params(known, ym1, ym2, granularity)

    # 해양관광은 배열 파라미터가 필요하다. 지역의 연안 유형을 먼저 물어
    # 조립해야 하므로 --param 으로 손으로 넣기 어렵다.
    marine_label = None
    if marine_region:
        try:
            marine_params, marine_label = marine.params_for(
                marine_region, ym1 or "202401", ym2 or "202412",
                cache_dir=cache_dir, session_file=session_file)
        except marine.MarineError as exc:
            raise QueryError(str(exc)) from exc
        base.update(marine_params)

    base.update(extra or {})

    targets = resolve_targets(regions, countries, sidos, festivals)
    targets += resolve_attractions(attractions, cache_dir=cache_dir,
                                   session_file=session_file)
    _reject_region_on_sido_axis(qid, source, holder, targets)
    meta = {"qid": qid, "출처": source, "대상수": max(len(targets), 1),
            "대상": [name for _, _, name in targets],
            "조건": dict(base), "축조건": [], "통합시안내": [],
            "축주의": [],
            "해양지역": marine_label,
            "알려진_파라미터": sorted(known)}
    if source == "색인":
        meta["이름"] = " / ".join(holder.get("names") or []) or "-"
    else:
        meta["이름"] = holder[qid]["name"]
        # 카탈로그가 적어 둔 함정(축 파라미터를 무시하는 지표 등)을 그대로
        # 전달한다. 검증하면서 알아낸 사실이므로 사용자가 봐야 한다.
        meta["주의"] = holder[qid].get("caution")

    if marine_label:
        meta["축조건"].append(f"해양관광 배열 파라미터 ({marine_label})")

    if not targets:
        frame = fetch_one(qid, source, holder, base, cache_dir=cache_dir,
                          session_file=session_file)
        return frame, meta

    pieces = []
    for kind, code, name in targets:
        params = dict(base)
        # 축 키를 여기서 이름 붙여 둔다. params에서 되찾으려 하면 이름
        # 파라미터(natNm, CNTRL_TAR_NM)까지 섞여 dict 순서에 기대게 된다.
        if kind == "지역":
            axis_key = _axis_key(known, _REGION_KEYS, "SGG_CD")
            note = codes.merged_city_note(code)
            if note:
                meta["통합시안내"].append(note)
        elif kind == "시도":
            axis_key = _axis_key(known, _SIDO_KEYS, "SGG_CD")
            # 시군구 축 지표에 시도 두 자리를 보내면 어떻게 되는지는
            # 지표마다 다르다. LN_04_01_022 는 시도 합계를 주지만
            # (2024-01 강원 11,299,486), 첫 시군구 값을 주는 지표도
            # 있다 — `vitality.py summary 강원`이 춘천시 값을 돌려주던
            # 것이 그 경우다. 어느 쪽인지는 응답의 지역명이 말해 준다.
            # 조용히 보내면 사용자는 그것을 시도 값으로 읽는다.
            # query_axis 표기는 184개 중 124개에만 있다. 표기가 없어도
            # **SGG_CD만 받고 SIDO_CD는 모르는** 지표라면 시군구 전용이다.
            시군구전용 = "SGG_CD" in known and "SIDO_CD" not in known
            if (source != "색인"
                    and (holder.get(qid) or {}).get("query_axis") != "시도"
                    and 시군구전용):
                meta["축주의"].append(
                    f"'{name}'(시도 두 자리)를 시군구 축 지표에 보냅니다. "
                    f"시도 합계가 올 수도, 그 시도의 첫 시군구 값이 올 "
                    f"수도 있습니다 — 표의 지역명을 확인하세요.")
        elif kind == "관광지":
            axis_key = _axis_key(known, _POI_KEYS, "CONT_ID")
        elif kind == "축제":
            axis_key = _axis_key(known, _FESTIVAL_KEYS, "FSTV_ID")
        else:
            axis_key = _axis_key(known, _COUNTRY_KEYS, "natCd")
            # 한류 계열은 NAT_CD에 코드가 아니라 한글 국가명을 받는다.
            # JP를 보내면 오류가 아니라 빈 배열이 와서, 사용자는 "일본은
            # 데이터가 없구나"로 읽는다.
            if (source != "색인"
                    and (holder.get(qid) or {}).get("query_axis") == "국가명"):
                code = name
        params[axis_key] = code

        # 비교 화면 지표(getByRegnAna 등)는 같은 코드를 배열 파라미터에도
        # 실어야 한다. 빼면 빈 배열이 아니라 0바이트 본문이 오고, 그때는
        # caution 이 화면에 나오지 않는다 — 오류 메시지만 나온다. 사용자가
        # 읽을 수 없는 곳에 적힌 규칙은 코드가 지킨다.
        # 지역·시도 축에만 채운다. 이 이름들은 시군구 코드를 담는
        # 자리라, 국가 축 지표가 같은 이름을 선언하면 CMPN_SGG_CD=JP가
        # 나간다. 지금 카탈로그에는 그런 조합이 없지만 막아 둔다.
        #
        # setdefault 만으로 사용자 값이 보존된다 — extra 는 이미 base 에
        # 병합돼 있고(위 base.update) params 는 base 의 사본이다.
        if kind in ("지역", "시도"):
            for mirror in _MIRROR_KEYS:
                if mirror in known:
                    params.setdefault(mirror, code)

        # 코드와 함께 이름도 받는 지표가 있다(외래관광객조사의 natNm).
        # 카탈로그가 선언한 경우에만 보낸다.
        if "natNm" in known:
            params["natNm"] = name
        meta["축조건"].append(f"{axis_key}={code} ({name})")
        piece = fetch_one(qid, source, holder, params, cache_dir=cache_dir,
                          session_file=session_file)
        if piece.empty:
            continue
        # 대상이 하나뿐이면 대상 컬럼은 모든 행에서 같은 값이라 정보가
        # 없다. 머리말에 이미 적혀 있으므로 표에서는 뺀다.
        if len(targets) > 1:
            piece.insert(0, TARGET_COLUMN, name)
        pieces.append(piece)

    if not pieces:
        return pd.DataFrame(), meta
    return pd.concat(pieces, ignore_index=True), meta


def sort_frame(frame, column, descending):
    """정렬한다. 없는 컬럼이면 그대로 둔다 — 조용히 다른 컬럼으로
    정렬해 버리는 것보다 정렬하지 않고 알리는 편이 낫다."""
    if not column or frame.empty:
        return frame, None
    if column not in frame.columns:
        return frame, f"'{column}' 컬럼이 없어 정렬하지 않았습니다."
    return frame.sort_values(column, ascending=not descending,
                             kind="mergesort").reset_index(drop=True), None


def _header(meta):
    """머리말은 '무엇을 보냈는가'만 적는다.

    "— 베트남"처럼 결과의 뜻을 단언하면 안 된다. natCd를 받아 놓고
    무시한 채 전체를 돌려주는 지표가 실제로 있기 때문이다
    (NAT_08_01_021이 그렇다). 보낸 조건은 우리가 아는 사실이고,
    돌아온 행이 그 조건으로 좁혀졌는지는 표를 봐야 안다.
    """
    lines = [f"{meta['qid']}  {meta['이름']}"]
    # 해양관광 배열 파라미터는 열 개가 넘어 머리말을 뒤덮는다.
    # 그것이 붙었다는 사실만 축조건에 적고 개별 키는 감춘다.
    sent = [f"{k}={v}" for k, v in sorted(meta["조건"].items())
            if "[" not in k]
    sent += meta["축조건"]
    if sent:
        lines.append("보낸 조건: " + ", ".join(sent))
    if meta["출처"] == "색인":
        # "컬럼 의미"만 말하면 축은 믿게 된다. 미검증이라는 것은 축도
        # 검증하지 않았다는 뜻이다 — BDT_01_01_001_4에 SGG_CD=51을
        # 보냈더니 전국 값이 왔다. 검증된 지표라면 caution이 그것을
        # 적어 두지만 미검증에는 적어 둘 자리가 없다.
        lines.append("[미검증] 색인에만 있는 지표입니다. 컬럼 의미도 "
                     "**축이 먹었는지도** 확인하지 않았습니다 — 컬럼명이 "
                     "원본 그대로 나오고, 보낸 조건이 무시된 채 전국 값이 "
                     "올 수도 있습니다. 응답의 지역·기간 컬럼을 눈으로 "
                     "맞춰 보세요.")
    else:
        lines.append(f"[검증됨:{meta['출처']}] 컬럼이 한글 라벨로 바뀌었습니다.")
    if meta.get("주의"):
        lines.append("주의: " + meta["주의"])
    # 축을 잘못 보낸 것은 **값이 왔을 때** 더 위험하다. 빈 표는 사용자도
    # 이상한 줄 알지만 그럴듯한 숫자는 그대로 리포트에 실린다.
    for note in meta.get("축주의") or ():
        lines.append("주의: " + note)
    return "\n".join(lines)


def _no_data_hint(meta, ym1=None, ym2=None):
    """왜 비었는지 짚어 준다. 짚을 수 있는 것부터 먼저 말한다.

    수록 시점을 아는 지표라면 "아직 안 나왔다"를 맨 앞에 놓는다.
    그것이 이유일 때가 가장 많고, 사용자가 스스로 알아낼 수 없는
    유일한 이유이기도 하다.
    """
    lines = []
    gap = period.explain_gap(meta["qid"], ym1, ym2)
    if gap:
        lines.append(gap)
        lines.append("")
    for note in meta.get("통합시안내") or ():
        lines.append(note)
        lines.append("")
    for note in meta.get("축주의") or ():
        lines.append(f"주의: {note}")
        lines.append("")

    # 기간을 아예 안 줬거나 한쪽만 준 것은 임의 조회에서 막지 않는다 —
    # 시점 재고 지표는 --to 하나로 부르는 것이 정상이기 때문이다. 그래서
    # 기간이 필요한 지표에 안 주면 조용히 빈 표가 온다. 짚어 준다.
    if "BASE_YM1" in (meta.get("알려진_파라미터") or ()):
        if not ym1 and not ym2:
            lines.append("기간을 주지 않았습니다. 이 지표는 기간을 "
                         "받습니다 — --period 작년 처럼 쓰세요.")
            lines.append("")
        elif not (ym1 and ym2):
            빠진 = "--to" if ym1 else "--from"
            lines.append(f"{빠진} 가 빠졌습니다. 이 지표는 시작과 끝을 "
                         f"함께 받습니다 — 한쪽만 알면 --period 를 쓰세요.")
            lines.append("")

    # 요청 기간이 통째로 수록 시점 뒤라면 이유는 그것 하나다. 그런데도
    # "파라미터가 틀렸다"까지 함께 내면, 2027년을 물었을 뿐인 사용자가
    # 맞는 파라미터를 찾아 헤맨다. 짚을 수 있을 때는 짚고 그만둔다.
    _, _, note = period.clamp(meta["qid"], ym1, ym2)
    if note and note["부름"] is None:
        return "\n".join(lines).rstrip()

    lines += [
        "행이 없습니다. 데이터랩은 실패를 여러 방식으로 표현합니다:",
        "  - 파라미터가 틀렸다 (특히 기간 형식과 조회 축)",
        "  - 그 조건에 데이터가 없다 (조사 대상이 아닌 국가·지역)",
        "  - 아직 발표되지 않은 달을 물었다",
        "  - 숨은 필수 파라미터가 빠졌다 (dispYn 등)",
    ]
    last = period.latest(meta["qid"])
    if last and not gap:
        # 프로브가 그 달에서 멈춘 지표는 "여기까지 확인했다"이지
        # "여기가 끝이다"가 아니다. 둘을 같은 말로 적지 않는다.
        tail = ("까지 확인했습니다" if period.at_anchor(meta["qid"])
                else "까지 나와 있습니다")
        lines.append(f"이 지표는 {last[:4]}-{last[4:]}{tail}.")
    lines += [
        f"이 지표가 받는다고 알려진 파라미터: "
        f"{', '.join(meta['알려진_파라미터']) or '알려진 것 없음'}",
        "  --param K=V 로 직접 지정해 다시 시도하세요.",
    ]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="데이터랩 지표를 임의 조건으로 조회한다")
    parser.add_argument("--qid", required=True)
    parser.add_argument("--region", action="append", default=[],
                        help="지역명 또는 시군구 코드. 여러 번 쓰면 비교표가 된다")
    parser.add_argument("--sido", action="append", default=[],
                        help="시도명 또는 두 자리 코드. 야간관광처럼 시도 축인 "
                             "지표에 쓴다")
    parser.add_argument("--attraction", action="append", default=[],
                        metavar="지역:이름",
                        help="관광지. 이름이 전국에서 유일하지 않아 지역을 "
                             "함께 받는다. 예: '강릉시:경포해수욕장'")
    parser.add_argument("--festival", action="append", default=[],
                        help="문화관광축제 이름 또는 FSTV_ID")
    parser.add_argument("--marine-region", default=None, metavar="지역",
                        help="해양관광(BY_TH_MARINE_*) 지표에 쓴다. 지역의 "
                             "연안 유형을 먼저 물어 배열 파라미터를 만든다")
    parser.add_argument("--country", action="append", default=[],
                        help="국가명 또는 국가 코드. 여러 번 쓸 수 있다")
    parser.add_argument("--period", default=None, metavar="기간",
                        help=period.HELP)
    parser.add_argument("--from", dest="ym1", metavar="YYYYMM")
    parser.add_argument("--to", dest="ym2", metavar="YYYYMM")
    parser.add_argument("--param", action="append", default=[], metavar="K=V")
    parser.add_argument("--format", default="table",
                        choices=sorted(table.RENDERERS))
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                        help="표에 보일 행 수. 0이면 전부")
    parser.add_argument("--sort", metavar="COLUMN")
    parser.add_argument("--desc", action="store_true")
    parser.add_argument("--out", metavar="FILE")
    args = parser.parse_args(argv)

    # 여기서는 --from 만 주거나 기간을 아예 안 주는 것도 정상이다.
    # 시점 재고 지표는 BASE_YM2 하나로 시점을 정한다.
    try:
        args.ym1, args.ym2 = period.from_args(
            args, anchor=period.ceiling(args.qid), allow_open_range=True)
    except period.PeriodError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    extra = {}
    for item in args.param:
        if "=" not in item:
            print(f"--param 은 K=V 형식이어야 합니다: {item}", file=sys.stderr)
            return 1
        key, value = item.split("=", 1)
        extra[key] = value

    try:
        frame, meta = run(args.qid, regions=args.region,
                          countries=args.country, sidos=args.sido,
                          attractions=args.attraction,
                          festivals=args.festival,
                          marine_region=args.marine_region,
                          ym1=args.ym1, ym2=args.ym2,
                          extra=extra, cache_dir=str(CACHE_DIR),
                          session_file=str(SESSION_FILE))
    except QueryError as exc:
        print(exc, file=sys.stderr)
        return 1
    except client.SessionExpired:
        print(f"세션이 만료됐습니다. 다시 로그인하세요:\n  {LOGIN_HINT}",
              file=sys.stderr)
        return 3
    except client.FetchError as exc:
        print(f"인출에 실패했습니다: {exc}\n"
              f"HTTP 200에 0바이트 본문이면 데이터랩이 그 지표를 더는 "
              f"제공하지 않는다는 뜻입니다.", file=sys.stderr)
        return 4

    frame, sort_note = sort_frame(frame, args.sort, args.desc)
    limit = None if args.limit == 0 else args.limit
    body = table.render(frame, args.format, limit)

    if args.out:
        pathlib.Path(args.out).write_text(body + "\n", encoding="utf-8")
        print(f"{len(frame)}행을 저장했습니다: {args.out}")
    else:
        if args.format in ("table", "md"):
            print(_header(meta))
            print()
        print(body)

    if frame.empty:
        print("\n" + _no_data_hint(meta, args.ym1, args.ym2),
              file=sys.stderr)
        return 4
    if sort_note:
        print("\n" + sort_note, file=sys.stderr)
    if args.format in ("table", "md") and not args.out:
        print("\n" + table.SOURCE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
