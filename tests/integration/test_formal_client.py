from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient


def test_formal_client_exposes_the_approved_brand_and_workspace_navigation():
    app = FastAPI()
    app.mount("/admin", StaticFiles(directory="static", html=True), name="admin")

    with TestClient(app) as client:
        response = client.get("/admin/index.html")

    assert response.status_code == 200
    assert "记忆宫殿 · Memory Palace OS" in response.text
    assert "登录您的工作空间" in response.text
    assert "指挥中心" in response.text
    assert "事件处置" in response.text
    assert "任务与审批" in response.text
    assert "组织记忆" in response.text
    assert "系统治理" in response.text
    assert 'value="admin"' not in response.text
    assert 'value="123456"' not in response.text
