"""사람이 쓴 지역명·국가명을 데이터랩 코드로 해석한다.

네트워크를 타지 않는다. data/sgg_codes.yaml과 data/nat_codes.yaml만 읽는다.
두 표 모두 데이터랩이 스스로 돌려준 값으로 만든 것이고, 우리가 지어낸
이름은 하나도 없다.

지역은 `SGG_CD`(시군구 5자리), 국가는 `natCd`(대개 두 글자)로 조회한다.
축이 다르므로 함수도 나눠 둔다 — 하나로 합치면 "강서"가 국가인지 지역인지
호출부가 알 수 없게 된다.
"""
import collections
import pathlib

import yaml

import workspace

# <skills>/<이름>/scripts/x.py 에서 parents[2] 가 skills 루트다. 사용자에게
# 보여 줄 안내 명령을 만드는 데만 쓴다 — 다른 스킬의 이름과 스크립트
# 이름을 문자열로 조립할 뿐, 그 스킬의 코드를 import하지 않는다.
_SKILLS_ROOT = pathlib.Path(__file__).resolve().parents[2]

DATA_DIR = pathlib.Path(__file__).resolve().parents[1] / "data"
CODES_PATH = DATA_DIR / "sgg_codes.yaml"
SIDO_CODES_PATH = DATA_DIR / "sido_codes.yaml"
NAT_CODES_PATH = DATA_DIR / "nat_codes.yaml"
FESTIVAL_CODES_PATH = DATA_DIR / "festival_codes.yaml"
_codes_cache = None
_sido_cache = None
_nat_cache = None
_festival_cache = None

# 국가 축에 섞여 있지만 나라가 아닌 코드. 데이터랩이 국가와 같은 축에서
# 집계하므로 표에서 지우지는 않되, "국가 목록"을 보여줄 때는 구분한다.
NON_COUNTRY_CODES = {"924", "929", "940", "943"}


def load_codes(path=None):
    """시군구 코드 마스터를 dict로 반환한다. 인자가 없으면 결과를 캐시한다."""
    global _codes_cache
    if path is not None:
        return yaml.safe_load(pathlib.Path(path).read_text(encoding="utf-8"))
    if _codes_cache is None:
        _codes_cache = yaml.safe_load(CODES_PATH.read_text(encoding="utf-8"))
    return _codes_cache


def load_nat_codes(path=None):
    """국가 코드 마스터를 dict로 반환한다. 인자가 없으면 결과를 캐시한다."""
    global _nat_cache
    if path is not None:
        return yaml.safe_load(pathlib.Path(path).read_text(encoding="utf-8"))
    if _nat_cache is None:
        _nat_cache = yaml.safe_load(NAT_CODES_PATH.read_text(encoding="utf-8"))
    return _nat_cache


def load_sido_codes(path=None):
    """시도 코드 마스터를 dict로 반환한다. 인자가 없으면 결과를 캐시한다."""
    global _sido_cache
    if path is not None:
        return yaml.safe_load(pathlib.Path(path).read_text(encoding="utf-8"))
    if _sido_cache is None:
        _sido_cache = yaml.safe_load(SIDO_CODES_PATH.read_text(encoding="utf-8"))
    return _sido_cache


def children(code, table=None):
    """통합시 산하 구의 (코드, 표시이름) 목록. 통합시가 아니면 빈 목록.

    수원시·전주시 같은 통합시는 코드가 둘로 산다. 시 전체를 가리키는
    코드(52110)와 구 코드(52111, 52113)다. 지표에 따라 시 코드로는
    값이 오지 않고 구 코드로만 온다 — 관광지 목록이 그렇다. 오류가
    아니라 빈 배열이 오므로, 구를 뒤져 보지 않으면 "관광지가 없는
    도시"로 보인다.
    """
    table = table if table is not None else load_codes()
    entry = table.get(str(code))
    if not entry or not entry.get("통합"):
        return []
    prefix = entry["시군구"] + " "
    return sorted(
        (child, f"{meta['시도']} {meta['시군구']}")
        for child, meta in table.items()
        if meta["시도"] == entry["시도"] and meta["시군구"].startswith(prefix))


def josa(word, with_final, without_final):
    """받침에 맞는 조사를 고른다. "'서울'는"은 사람이 쓴 글로 보이지 않는다.

    한글이 아닌 글자로 끝나면(코드 "11" 등) 받침이 없는 쪽을 쓴다 —
    숫자를 읽는 방식은 사람마다 달라서 어느 쪽이든 어색할 수 있고,
    없는 쪽이 덜 어색하다.
    """
    text = str(word or "").strip()
    if not text:
        return without_final
    last = text[-1]
    if not "가" <= last <= "힣":
        return without_final
    return with_final if (ord(last) - 0xAC00) % 28 else without_final


def sido_hint(query):
    """'서울'처럼 시도 이름을 시군구 자리에 넣었을 때의 안내. 아니면 None.

    데이터랩의 지역 지표는 시군구 단위다. 시도 전체 리포트는 없다.
    후보 스물다섯 개만 늘어놓으면 초보자는 "서울은 안 되는구나"에서
    멈춘다. 대신 시도 단위로 할 수 있는 일을 알려 준다.
    """
    hits = resolve_sido(query)
    if len(hits) != 1:
        return None
    code, name = hits[0]
    return (
        f"'{query}'{josa(query, '은', '는')} 시도({name})이기도 합니다. "
        f"데이터랩의 지역 지표는 "
        f"시군구 단위라 시도 전체 리포트는 만들 수 없습니다.\n"
        f"  시도 안에서 순위를 보려면:\n"
        f"    python3 {workspace.display_path(_SKILLS_ROOT, 'datalab-query', 'rank.py')} "
        f"--qid LN_04_01_022 --column 방문자수 --period 작년 --sido {query}\n"
        f"  구·시를 나란히 놓으려면:\n"
        f"    python3 {workspace.display_path(_SKILLS_ROOT, 'region-market-scan', 'compare.py')} "
        f"--region <구1> --region <구2> --period 작년 --out /tmp/compare.html")


def merged_city_note(code, table=None):
    """통합시면 안내 문장, 아니면 None.

    수원·전주 같은 통합시는 시 전체 코드로 부르면 지표에 따라 빈 배열이
    온다. 관광사업체·인기관광지·유사지역이 그렇고, 방문자 수는 나온다.

    **한때 열여섯 지표가 더 비어 있었는데 그것은 지표 탓이 아니었다.**
    `sggIntgYnFlag` 가 시 쪽과 구 쪽을 가르는데 카탈로그가 "N"을 못
    박고 있었다(2026-08-24). 인출 계층이 이제 모시 코드가 빈손이면
    "Y"로 한 번 되묻는다 — 읍면동 성·연령 열둘이 그때 살아났다.
    그래도 남는 빈 배열이 있어 이 안내는 계속 필요하다.
    같은 리포트 안에서 어떤 표는 차 있고 어떤 표는 비는 이유가 이것인데,
    그 사실을 말해 주지 않으면 "이 도시에는 숙박업소가 없다"로 읽힌다.

    **산하 구를 더해도 시가 되지 않는다.** 구 사이를 오간 사람이 구마다
    한 번씩 세어지기 때문이다 — 2024년 1월 수원시 4개 구 합은
    17,344,087명인데 수원시는 14,883,969명으로 16% 적다(포항 11%,
    전주 9%). 구별 표를 더해 "시 전체"라고 적으면 부풀린 숫자가 된다.
    """
    kids = children(code, table)
    if not kids:
        return None
    entry = (table if table is not None else load_codes())[str(code)]
    names = ", ".join(name.split()[-1] for _, name in kids)
    return (f"{entry['시군구']}는 통합시입니다. 지표에 따라 시 전체 코드로는 "
            f"값이 오지 않습니다(관광사업체·인기관광지·유사지역 등). "
            f"구 단위로 보려면 --region '{entry['시군구']} {kids[0][1].split()[-1]}' "
            f"처럼 쓰세요. 산하 구: {names}. "
            f"구별 값을 더해도 시 전체가 되지 않습니다 — 구 사이를 오간 "
            f"사람이 구마다 세어져 합이 10%가량 부풀려집니다.")


def resolve_sido(query, codes=None):
    """시도 문자열을 (코드, 시도명) 목록으로 해석한다.

    시군구표에서 앞 두 자리를 잘라 만들지 않는다. 그러면 산하 시군구가
    없는 세종특별자치시가 빠진다.
    """
    codes = codes or load_sido_codes()
    text = str(query).strip()
    if not text:
        return []
    if text in codes:
        return [(text, codes[text])]
    return sorted((code, name) for code, name in codes.items() if text in name)


def load_festival_codes(path=None):
    """문화관광축제 코드 마스터를 dict로 반환한다."""
    global _festival_cache
    if path is not None:
        return yaml.safe_load(pathlib.Path(path).read_text(encoding="utf-8"))
    if _festival_cache is None:
        _festival_cache = yaml.safe_load(
            FESTIVAL_CODES_PATH.read_text(encoding="utf-8"))
    return _festival_cache


def resolve_festival(query, codes=None):
    """축제 문자열을 (FSTV_ID, "축제명 (시군구)") 목록으로 해석한다.

    데이터랩에 축제 목록 API가 없어서 표를 한 번 만들어 두었다. 지역·국가와
    마찬가지로 여러 곳에 걸리면 전부 돌려주고 하나를 고르지 않는다.
    """
    codes = codes or load_festival_codes()
    text = str(query).strip()
    if not text:
        return []
    upper = text.upper()
    if upper in codes:
        entry = codes[upper]
        return [(upper, f'{entry["축제명"]} ({entry["시군구"]})')]

    def label(entry):
        return f'{entry["축제명"]} ({entry["시군구"]})'

    exact = [(code, label(e)) for code, e in codes.items()
             if e["축제명"] == text]
    if exact:
        return sorted(exact)

    partial = sorted((code, label(e)) for code, e in codes.items()
                     if text in e["축제명"])
    if partial:
        return partial

    # 사람은 "화천 산천어축제"라고 띄어 쓴다. 데이터랩 표기가
    # 붙여쓰기라고 해서 사용자가 그렇게 써야 하는 것은 아니다.
    빈칸없이 = text.replace(" ", "")
    if 빈칸없이 != text:
        return sorted((code, label(e)) for code, e in codes.items()
                      if 빈칸없이 in e["축제명"].replace(" ", ""))
    return []


def nearest_festivals(query, codes=None, limit=3):
    """겹치는 낱말이 많은 축제를 후보로 돌려준다. 없으면 빈 목록.

    데이터랩은 "진주유등축제"로 적지만 사람은 "진주남강유등축제"라
    부른다. 빈손으로 돌려보내는 대신 가까운 것을 알려 준다.

    **고르지는 않는다.** 확신할 수 없으므로 후보를 주고 사용자가 정한다 —
    이 저장소가 지역·국가에서 지키는 규칙과 같다.
    """
    codes = codes or load_festival_codes()
    text = str(query).strip().replace(" ", "")
    if not text:
        return []
    # 두 글자씩 끊어 겹침을 센다. 한국어 축제 이름은 "유등축제"처럼
    # 두 글자 단위로 뜻이 나뉘는 경우가 많다.
    #
    # **흔한 조각은 값을 낮춘다.** 그냥 세면 "안동국제탈춤페스티벌"이
    # "페스"·"스티"·"티벌" 셋으로 대구치맥페스티벌을 이기고, 정작
    # "안동"·"탈춤" 둘뿐인 안동탈춤축제가 밀린다. 축제 이름의 꼬리말은
    # 어느 축제에나 있어서 아무것도 가려내지 못한다.
    조각 = {text[i:i + 2] for i in range(len(text) - 1)}
    빈도 = collections.Counter()
    for entry in codes.values():
        이름 = entry["축제명"].replace(" ", "")
        for 두글자 in {이름[i:i + 2] for i in range(len(이름) - 1)}:
            빈도[두글자] += 1
    점수 = []
    for code, entry in codes.items():
        이름 = entry["축제명"].replace(" ", "")
        걸린 = [c for c in 조각 if c in 이름]
        if len(걸린) >= 2:
            값 = sum(1.0 / 빈도[c] for c in 걸린)
            점수.append((-값, code,
                         f'{entry["축제명"]} ({entry["시군구"]})'))
    점수.sort()
    return [(code, 이름) for _, code, 이름 in 점수[:limit]]


def is_sido(code):
    """시도 코드인지 판정한다. 시도는 두 자리 숫자, 시군구는 다섯 자리다.

    길이만 보면 "강서" 같은 두 글자 지역명까지 시도 코드로 오판한다.
    이 함수는 코드 분류기이므로 숫자인지부터 확인한다.
    """
    text = str(code).strip()
    return text.isdigit() and len(text) == 2


def display_name(code, codes=None):
    """코드를 '시도 시군구' 형태의 표시 이름으로 만든다."""
    entry = (codes or load_codes())[str(code).strip()]
    return f'{entry["시도"]} {entry["시군구"]}'


def resolve_region(query, codes=None):
    """지역 문자열을 (코드, 표시이름) 목록으로 해석한다.

    다섯 자리 숫자를 넣으면 그 코드 하나만 돌려준다. 그 밖에는 시도명과
    시군구명 양쪽에 대해 부분일치로 찾는다. 일치가 여러 건이면 전부
    돌려준다 — 어느 하나를 임의로 고르지 않는다. 호출부가 사용자에게
    후보를 보여주고 다시 묻는 것이 맞다.
    """
    codes = codes or load_codes()
    text = str(query).strip()
    if not text:
        return []
    if text in codes:
        return [(text, display_name(text, codes))]

    exact = []
    partial = []
    for code, entry in codes.items():
        full = f'{entry["시도"]} {entry["시군구"]}'
        if text in (entry["시군구"], full):
            exact.append((code, full))
        elif text in entry["시군구"] or text in entry["시도"] or text in full:
            partial.append((code, full))
    # 정확히 그 이름인 곳이 있으면 그것만 준다. "중구"처럼 여러 시도에
    # 같은 이름이 있으면 여전히 여러 건이지만, 부분일치로 딸려 온 것들에
    # 파묻히지는 않는다.
    if exact:
        # 통합시 산하 구는 이름이 "포항시 북구"여서 "북구"로는 정확일치에
        # 걸리지 않는다. exact 만 주면 광역시 북구 넷만 보이고 포항시
        # 북구는 후보에서 통째로 사라진다 — 사람은 그냥 "북구"라 부른다.
        # 마지막 낱말이 정확히 같은 것만 더한다("성남시"가 분당구를
        # 딸고 오지 않도록).
        산하 = [(c, n) for c, n in partial
                if codes[c]["시군구"].split()[-1] == text]
        return sorted(set(exact) | set(산하))

    # "서울 중구"·"강원 강릉"처럼 시도와 시군구를 함께 말한 경우.
    # **되물은 보람이 있으려면 이것을 받아야 한다** — "중구"가 여섯 곳에
    # 걸려 후보를 보여 주면 사용자는 "서울 중구"라고 답한다. 정식 명칭
    # 전체("서울특별시 중구")만 받는 것은 사람이 쓰는 말이 아니다.
    묶음 = _split_sido(text, codes)
    if 묶음 is not None:
        return 묶음

    # "포항 북구"·"성남 분당"처럼 통합시 이름을 앞에 붙여 부른 경우.
    묶음 = _split_mother(text, codes)
    if 묶음:
        return 묶음

    return sorted(partial)


def _split_mother(text, codes):
    """"포항 북구"·"성남 분당"처럼 통합시 이름을 앞에 붙여 부른 산하 구.

    **좁히려는 사용자가 벌을 받으면 안 된다.** "북구"는 다섯 곳에
    걸리므로 후보를 보여 주면 사용자는 "포항 북구"라고 답한다. 그런데
    표에 적힌 이름은 "포항시 북구"라 '시' 한 글자 때문에 부분일치가
    깨지고, 시도 조합도 아니어서 빈손이 됐다.

    앞말은 "포항시"·"포항", 뒷말은 "북구"·"북"까지 받는다. 사이의
    띄어쓰기는 있어도 없어도 같다.
    """
    찾음 = []
    for code, entry in codes.items():
        이름 = entry["시군구"]
        if " " not in 이름:
            continue
        모시, 구 = 이름.split(" ", 1)
        머리들 = {모시, 모시.rstrip("시")}
        꼬리들 = {꼬 for 꼬 in (구, 구.rstrip("구")) if 꼬}
        for 머리 in 머리들:
            for 꼬리 in 꼬리들:
                for 사이 in ("", " "):
                    if text == 머리 + 사이 + 꼬리:
                        찾음.append((code, f'{entry["시도"]} {이름}'))
    return sorted(set(찾음))


def _split_sido(text, codes):
    """"서울 중구"를 시도와 시군구로 갈라 찾는다. 아니면 None.

    시도가 틀린 조합("부산 강릉")은 빈 목록을 준다 — 시군구 이름만 보고
    강릉을 주면 사용자는 자기가 묻지 않은 지역의 숫자를 본다.
    """
    시도들 = {entry["시도"] for entry in codes.values()}
    # 그 자체가 시도 이름이면 조합으로 읽지 않는다. "서울특별시"를
    # "서울" + "특별시"로 가르면 시군구 "특별시"를 찾다가 빈손이 된다.
    if text in 시도들 or any(시도.startswith(text) for 시도 in 시도들):
        return None

    후보 = []
    for 시도 in 시도들:
        # 서울특별시 · 서울 · 강원도(앞 두 자 + 도). 도 단위를 "강원도"로
        # 부르는 것이 자연스럽고, 광역시에 붙어도 매칭되지 않아 무해하다.
        for 앞 in (시도, 시도[:2], 시도[:2] + "도"):
            for 사이 in ("", " "):
                머리 = 앞 + 사이
                if not text.startswith(머리) or len(text) == len(머리):
                    continue
                꼬리 = text[len(머리):].strip()
                if not 꼬리:
                    continue
                후보.append((시도, 꼬리))
    if not 후보:
        return None
    찾음 = []
    for 시도, 꼬리 in 후보:
        for code, entry in codes.items():
            if entry["시도"] != 시도:
                continue
            if 꼬리 in (entry["시군구"], entry["시군구"].rstrip("시군구")):
                찾음.append((code, f'{entry["시도"]} {entry["시군구"]}'))
    return sorted(set(찾음))


class CodeError(Exception):
    """지역 인자를 코드로 바꿀 수 없을 때. 사용자 입력이 원인이다."""


def resolve_axis_code(value, *, allow_sido=True, region_codes=None,
                      sido_codes=None):
    """CLI가 받은 지역 인자를 축 코드로 바꾼다. 못 바꾸면 CodeError.

    **왜 걸러야 하는가.** 데이터랩은 유효하지 않은 SGG_CD를 오류로
    알려 주지 않는다. 조용히 첫 시군구(서울 종로구)로 대체해 값을
    준다 — "정선군"이라고 적어 보내면 종로구 숫자가 돌아오고, 응답에
    "종로구"라고 적혀 있어도 사용자는 자기가 물은 지역으로 읽는다.

    **`allow_sido=False`는 시군구 축 도구가 쓴다.** 시도 코드도 같은
    사고를 낸다 — "강원"이 춘천시, "광주"가 광주 동구가 된다. 축을
    아는 쪽에서 막아야 한다.

    시군구를 먼저 찾는다. 그다음에만 시도를 본다 — 반대로 하면
    `allow_sido=False`에서 "정선군"까지 시도 검사에 걸려 튕긴다.
    """
    text = str(value).strip()
    table = region_codes or load_codes()
    sido = sido_codes or load_sido_codes()

    if text in table:
        return text

    hits = resolve_region(text, table)
    exact = [(c, n) for c, n in hits if n.split()[-1] == text]
    if len(exact) == 1:
        return exact[0][0]

    # 시도를 시군구 부분일치보다 먼저 본다. resolve_region 은 시도명으로도
    # 부분일치하므로, 시군구를 먼저 받으면 "강원"이 강원도 안 시군구
    # 열여덟 곳에 걸려 "모호하다"고 튕긴다.
    if text in sido or resolve_sido(text, sido):
        if not allow_sido:
            이름 = sido.get(text) or resolve_sido(text, sido)[0][1]
            말 = (f"'{text}'({이름})는 시도입니다. 이 지표는 시군구 단위라 "
                  f"시도를 넣으면 그 시도의 첫 시군구 값이 옵니다.")
            # 같은 이름의 시군구가 따로 있으면 알려 준다. "광주"는
            # 광주광역시이면서 경기도 광주시(41610)이기도 하다 —
            # 시도라고만 하면 후자를 찾던 사람이 길을 잃는다.
            같은이름 = [(c, n) for c, n in resolve_region(text, table)
                        if text in table[c]["시군구"]]
            if 같은이름:
                목록 = "\n".join(f"  {c}  {n}" for c, n in 같은이름)
                말 += f"\n같은 이름의 시군구를 찾는다면:\n{목록}"
            raise CodeError(말)
        if text in sido:
            return text
        sido_hits = resolve_sido(text, sido)
        if len(sido_hits) == 1:
            return sido_hits[0][0]
        목록 = "\n".join(f"  {c}  {n}" for c, n in sido_hits)
        raise CodeError(f"'{text}'에 여러 시도가 걸립니다:\n{목록}")

    if len(hits) == 1:
        return hits[0][0]
    if len(hits) > 1:
        목록 = "\n".join(f"  {c}  {n}" for c, n in hits)
        raise CodeError(f"'{text}'에 여러 지역이 걸립니다:\n{목록}")

    무엇 = ("시군구 다섯 자리·시군구 이름" if not allow_sido
            else "시군구 다섯 자리·시도 두 자리·지역 이름")
    raise CodeError(f"{무엇} 중 하나여야 합니다: {text}")


def resolve_country(query, codes=None):
    """국가 문자열을 (코드, 국가명) 목록으로 해석한다.

    코드를 그대로 넣으면 그 하나만 돌려준다. 그 밖에는 국가명 부분일치로
    찾고, 여러 건이면 전부 돌려준다. 지역 해석과 같은 이유로 임의로 하나를
    고르지 않는다 — "기니"는 기니·적도 기니·기니비사우 셋에 걸린다.

    코드 비교는 대문자로 맞춘다. 데이터랩의 국가 코드는 대문자이지만
    사람은 "cn"이라고 쓰기 때문이다.
    """
    codes = codes or load_nat_codes()
    text = str(query).strip()
    if not text:
        return []
    upper = text.upper()
    if upper in codes:
        return [(upper, codes[upper])]

    # 이름이 정확히 같은 것을 먼저 본다. 그러지 않으면 "미국"이
    # 미국령 사모아·미국령 태평양군도에 파묻혀 "여러 건"으로 거부된다.
    exact = [(code, name) for code, name in codes.items() if name == text]
    if exact:
        return sorted(exact)

    partial = sorted((code, name) for code, name in codes.items()
                     if text in name)
    if partial:
        return partial

    # 여기까지 못 찾았으면 사람이 쓰는 꼬리말을 벗겨 한 번 더 본다.
    # "일본인 관광객"처럼 말하는 것이 자연스럽고, 에이전트는 그 말을
    # 그대로 --country 로 옮긴다.
    #
    # **원래 이름으로 먼저 찾은 뒤에만 벗긴다.** 스페인·바레인·
    # 리히텐슈타인·팔레스타인이 "인"으로 끝난다 — 무조건 벗기면
    # 스페인이 "스페"가 되어 사라진다.
    # 널리 쓰는 다른 표기. "USA"·"UAE"는 두 글자 코드가 아니라
    # 부분일치에도 안 걸려 빈손이 됐다.
    별칭 = COUNTRY_ALIASES.get(text) or COUNTRY_ALIASES.get(upper)
    if 별칭:
        return resolve_country(별칭, codes)

    풀어쓴 = _strip_nationality(text)
    if 풀어쓴 and 풀어쓴 != text:
        return resolve_country(풀어쓴, codes)
    return []


# 데이터랩 표기와 다르지만 널리 쓰는 이름. 근거가 분명한 것만 담는다.
COUNTRY_ALIASES = {
    "타이완": "대만",
    "차이나": "중국",
    "재팬": "일본",
    # 세 글자 약칭. 데이터랩 코드는 두 글자(US·AE·GB)라 그대로는
    # 코드로도 이름으로도 걸리지 않는다.
    "USA": "미국",
    "UAE": "아랍에미리트",
    "UK": "영국",
}


def nationality_name(text):
    """"일본인 관광객" 같은 말에서 국가 이름만 남긴다.

    응답의 국적 이름과 직접 견주는 곳(`inbound-region-scan`)이 쓴다 —
    그쪽은 코드 표를 거치지 않으므로 이 정리를 스스로 해야 한다.
    벗겨서 아무것도 남지 않으면 원래 말을 그대로 돌려준다.
    """
    남은 = _strip_nationality(text)
    return 남은 or str(text).strip()


def _strip_nationality(text):
    """"일본인 관광객"에서 "일본"을 남긴다. 못 벗기면 빈 문자열."""
    남은 = text
    for 꼬리 in ("관광객", "방문객", "여행객", "사람", "분들", "인"):
        if 남은.endswith(꼬리) and len(남은) > len(꼬리):
            남은 = 남은[: -len(꼬리)].strip()
    남은 = COUNTRY_ALIASES.get(남은, 남은)
    return 남은


def _main(argv=None):
    """코드 조회 CLI. `python3 codes.py region 강서` 처럼 쓴다."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="데이터랩 지역·국가 코드 조회")
    parser.add_argument("kind",
                        choices=["region", "sido", "country", "festival"])
    parser.add_argument("query", nargs="*", default=[])
    args = parser.parse_args(argv)

    text = " ".join(args.query)
    if args.kind == "region":
        hits = (resolve_region(text) if text
                else sorted((c, display_name(c)) for c in load_codes()))
    elif args.kind == "sido":
        hits = (resolve_sido(text) if text
                else sorted(load_sido_codes().items()))
    elif args.kind == "festival":
        hits = (resolve_festival(text) if text
                else sorted((c, f'{e["축제명"]} ({e["시군구"]})')
                            for c, e in load_festival_codes().items()))
    else:
        hits = (resolve_country(text) if text
                else sorted(load_nat_codes().items()))

    if not hits:
        print(f"일치하는 항목이 없습니다: {text}", file=sys.stderr)
        return 1
    for code, name in hits:
        print(f"{code}\t{name}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_main())
