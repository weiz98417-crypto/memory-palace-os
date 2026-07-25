"""
Locust load test for Memory Palace OS.
Usage: locust -f scripts/locustfile.py --host=http://localhost:8000
"""
from locust import HttpUser, task, between


class MemoryPalaceUser(HttpUser):
    wait_time = between(0.5, 2)

    @task(3)
    def demo_send_emergency(self):
        """Simulate emergency incident report"""
        self.client.post("/demo/send", json={
            "content": "景区西门有游客受伤了需要紧急处理",
            "from_user": "load_test",
        })

    @task(5)
    def demo_send_chat(self):
        """Simulate daily tourist query"""
        self.client.post("/demo/send", json={
            "content": "景区附近有什么好吃的餐厅推荐",
            "from_user": "load_test",
        })

    @task(1)
    def health_check(self):
        self.client.get("/health")

    @task(1)
    def admin_stats(self):
        self.client.get("/demo/stats")
