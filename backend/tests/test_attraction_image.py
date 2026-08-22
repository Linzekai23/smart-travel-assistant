"""景点图片服务：必应抓取解析 + 缓存（全 mock，无网络）。"""
import urllib.parse

from app.api.attraction_image import AttractionImageService, MEDIAURL_RE


class FakeResponse:
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code


BING_HTML = """<html><div class="mimg"><a href="/images/search?view=detailV2&mediaurl=https%3a%2f%2fimg.mala.cn%2fforum%2f202305%2f09%2f093421g0n4jjjejl9t880j.jpg&amp;exph=933&amp;expw=1400">\
<img src="https://tse2-mm.cn.bing.net/th/id/OIP-C.ymBRyq5z?w=217"></a></div></html>"""


class FakeHttp:
    """记录每次请求的 name，返回伪造必应 HTML。"""

    def __init__(self, html: str = BING_HTML, status: int = 200) -> None:
        self.html = html
        self.status = status
        self.calls: list[str] = []

    def __call__(self, url, **kwargs):
        self.calls.append(url)
        return FakeResponse(self.html, self.status)


def _make_service(http=None, cache_path=None):
    # 缓存路径必须显式传入（None 会落到真实 data/，污染/命中真实缓存）
    assert cache_path is not None
    return AttractionImageService(cache_path=cache_path, http_get=http or FakeHttp())


def test_extract_first_mediaurl():
    m = MEDIAURL_RE.search(BING_HTML)
    assert m is not None
    # mediaurl 是 URL-encoded，解码后为原图地址
    assert urllib.parse.unquote(m.group(1)) == "https://img.mala.cn/forum/202305/09/093421g0n4jjjejl9t880j.jpg"


def test_get_image_url_fetches_and_returns_first_result(tmp_path):
    http = FakeHttp()
    svc = _make_service(http, tmp_path / "imgs.json")
    assert svc.get_image_url("宽窄巷子") == "https://img.mala.cn/forum/202305/09/093421g0n4jjjejl9t880j.jpg"
    assert len(http.calls) == 1
    assert urllib.parse.quote("宽窄巷子") in http.calls[0]  # 景点名作为查询词


def test_get_image_url_caches_and_does_not_refetch(tmp_path):
    http = FakeHttp()
    cache = tmp_path / "imgs.json"
    svc = _make_service(http, cache)
    svc.get_image_url("宽窄巷子")
    svc2 = AttractionImageService(cache_path=cache, http_get=http)  # 新实例读缓存
    assert svc2.get_image_url("宽窄巷子") == "https://img.mala.cn/forum/202305/09/093421g0n4jjjejl9t880j.jpg"
    assert len(http.calls) == 1  # 第二次未再请求
    assert cache.exists() and "宽窄巷子" in cache.read_text(encoding="utf-8")


def test_get_image_url_returns_none_on_failure(tmp_path):
    http = FakeHttp(status=503)
    svc = _make_service(http, tmp_path / "imgs.json")
    assert svc.get_image_url("宽窄巷子") is None
    assert http.calls and urllib.parse.quote("宽窄巷子") in http.calls[0]


def test_get_image_url_returns_none_when_no_mediaurl(tmp_path):
    http = FakeHttp(html="<html>no results</html>")
    svc = _make_service(http, tmp_path / "imgs.json")
    assert svc.get_image_url("不存在的景点") is None
