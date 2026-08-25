"""qid 카탈로그를 적용해 데이터랩 원시 응답을 tidy DataFrame으로 바꾼다."""
import html
import pathlib
import re
import sys

import pandas as pd
import yaml

import client

CATALOG_PATH = pathlib.Path(__file__).resolve().parents[1] / "catalog" / "qid_catalog.yaml"
_catalog_cache = None


def load_catalog(path=None):
    """카탈로그 YAML을 읽어 dict로 반환한다. 인자가 없으면 결과를 캐시한다."""
    global _catalog_cache
    if path is not None:
        return yaml.safe_load(pathlib.Path(path).read_text())
    if _catalog_cache is None:
        _catalog_cache = yaml.safe_load(CATALOG_PATH.read_text())
    return _catalog_cache


# 인출 실패 사유를 사람이 읽는 말로 옮긴다. 사유 코드는 스킬마다 있는
# collect 계층이 만들지만 뜻은 같으므로 여기 한 곳에 둔다 — 두 벌로 두었더니
# 한쪽(비교 리포트)만 번역을 빠뜨려 코드가 그대로 화면에 나왔다.
FETCH_REASON_TEXT = {
    "데이터없음": "그 조건으로 값이 오지 않았습니다",
    "미발표": "요청한 기간이 아직 발표되지 않았습니다",
    "세션만료": "로그인 세션이 필요합니다",
    "인출실패": "호출 자체가 실패했습니다 (네트워크·프록시)",
}


def caution_html(text):
    """카탈로그 `caution` 을 리포트에 실을 HTML 로 만든다.

    카탈로그는 사람과 에이전트가 함께 읽는 곳이라 강조에 마크다운을
    쓴다(`**...**`, 백틱). 그것을 그대로 이스케이프해 싣고 있었더니
    리포트에 별표와 백틱이 날것으로 보였다 — 정작 강조하려던 문장이
    가장 읽기 나쁜 문장이 됐다.

    **이스케이프를 먼저 하고 그 다음에 변환한다.** 순서를 바꾸면
    caution 안의 `<` 가 태그로 살아난다.

    **결과를 HTML 속성에 넣지 마라.** 아래에서 `quote=False` 로
    이스케이프하므로 따옴표가 그대로 남는다 — 텍스트 노드에서는
    "'대한민국'이 들어 있다"를 읽히게 하는 이득이지만, `title="…"`
    같은 자리에 쓰면 그 순간 따옴표 탈출이 된다.
    """
    # quote=False 인 이유: 이 문자열은 속성이 아니라 텍스트 노드로
    # 들어간다. 기본값으로 두면 caution 안의 작은따옴표가 `&#x27;`
    # 로 보인다 — "'대한민국'이 들어 있다" 가 읽을 수 없게 된다.
    escaped = html.escape(str(text or ""), quote=False)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped, flags=re.S)
    escaped = re.sub(r"`([^`]+?)`", r"<code>\1</code>", escaped)
    return escaped


def reason_text(reason):
    """사유 코드를 사람이 읽는 말로. 모르는 코드는 그대로 돌려준다."""
    return FETCH_REASON_TEXT.get(reason, reason)


def fetch_qid(qid, params, *, catalog=None, cache_dir=None, session_file=None):
    """카탈로그의 fixed_params·auth·endpoint를 적용해 데이터를 인출한다.

    데이터랩에는 데이터 API가 둘 있다. 대부분은 getTempleteData.do를
    쓰지만 피벗 그리드 화면은 getGridData.do를 쓴다. 주소를 틀리면
    오류가 아니라 빈 배열이 오므로, 어느 쪽인지는 카탈로그가 적어 둔다.
    """
    entry = (catalog or load_catalog())[qid]
    merged = dict(entry.get("fixed_params") or {})
    merged.update(params)
    endpoint = (client.GRID_ENDPOINT
                if entry.get("endpoint") == "grid" else None)
    return client.fetch(qid, merged, auth=entry["auth"], endpoint=endpoint,
                        cache_dir=cache_dir, session_file=session_file)


def _정리(value):
    """문자열 값에서 서식으로 들어온 공백을 없앤다. 값은 건드리지 않는다."""
    if not isinstance(value, str):
        return value
    # 연속 두 칸 이상은 자간 벌리기다. 한 칸은 낱말 사이라 남긴다.
    return re.sub(r"[ \u3000]{2,}", "", value).strip()


def to_frame(qid, rows, catalog=None):
    """원시 레코드를 카탈로그 라벨이 적용된 DataFrame으로 변환한다."""
    entry = (catalog or load_catalog())[qid]
    columns = entry["columns"]
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=[m["label"] for m in columns.values()])

    unknown = [c for c in df.columns if c not in columns]
    if unknown:
        print(f"[경고] {qid}: 카탈로그에 없는 컬럼 {unknown}. "
              f"원본명을 유지합니다. 카탈로그 갱신이 필요할 수 있습니다.",
              file=sys.stderr)

    # 데이터랩이 "강원특별자치도 강릉시 "처럼 끝에 공백을 붙여 주는
    # 컬럼이 있다. 그대로 CSV로 뽑아 다른 표와 합치면 조인 키가 어긋나
    # 한 행도 맞지 않는다. 앞뒤 공백은 값이 아니라 서식이다.
    #
    # **카탈로그에 없는 컬럼까지 정리한다.** 라벨을 못 붙이는 컬럼이야말로
    # 카탈로그가 낡았을 때 나타나는 것이고, 조인 키가 어긋나는 문제는
    # 거기에도 똑같이 있다.
    #
    # **가운데 연속 공백도 지운다.** 데이터랩은 두 글자 낱말을 네 글자
    # 폭에 맞추려 자간을 벌린다 — NAT_07_01_005 의 입국 목적이
    # "관      광"·"공      용"으로 온다. 화면 정렬용 서식인데 그대로
    # 두면 표에 그 모양으로 실리고, `--where 목적=관광` 이 걸리지
    # 않는다. 공백 하나는 건드리지 않는다("강원특별자치도 강릉시").
    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].map(_정리)

    rename = {}
    for col, meta in columns.items():
        if col not in df.columns:
            continue
        rename[col] = meta["label"]
        if meta["type"] == "float":
            df[col] = pd.to_numeric(df[col], errors="coerce").astype(float)
        elif meta["type"] == "int":
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.rename(columns=rename)
