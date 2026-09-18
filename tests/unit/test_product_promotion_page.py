from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[2]
PRODUCT_DIR = ROOT / "static" / "product"


def test_product_promotion_page_is_a_self_contained_file():
    app = FastAPI()
    app.mount("/product", StaticFiles(directory=PRODUCT_DIR, html=True))

    with TestClient(app) as client:
        page = client.get("/product/")

    assert page.status_code == 200
    assert "记忆宫殿" in page.text
    assert "让每一次现场处置" in page.text
    assert "多场地、多岗位协同、依赖专家经验的运营型企业" in page.text
    assert 'id="fit"' in page.text
    assert "设备与安全异常" in page.text
    assert "客户投诉与服务事件" in page.text
    assert "巡检与整改" in page.text
    assert "专家交接与经验传承" in page.text
    assert "业务架构" in page.text
    assert "技术架构" in page.text
    assert "Canonical Ingress" in page.text
    assert "Redis Streams" in page.text
    assert "PostgreSQL" in page.text
    assert "PostgreSQL pgvector" in page.text
    assert 'role="tablist"' in page.text
    assert 'id="business-panel"' in page.text
    assert 'id="technical-panel"' in page.text
    assert 'href="/admin/"' not in page.text
    assert 'href="/assistant/"' not in page.text
    assert 'href="/simulator/wecom/"' not in page.text
    assert 'src="/admin/' not in page.text
    assert '<link rel="stylesheet"' not in page.text
    assert "<script src=" not in page.text
    assert "assets/" not in page.text
    assert "data:image/png;base64," in page.text
    assert "data:image/svg+xml;base64," in page.text
    assert "<style>" in page.text
    assert "const architectureTabs" in page.text


def test_main_registers_product_redirect_and_static_mount():
    source = (ROOT / "main.py").read_text(encoding="utf-8")

    assert '@app.get("/product", include_in_schema=False)' in source
    assert 'RedirectResponse(url="/product/", status_code=302)' in source
    assert 'StaticFiles(directory="static/product", html=True)' in source
