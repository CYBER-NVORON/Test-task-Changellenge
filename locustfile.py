import random
import uuid

from locust import HttpUser, between, task


class DeviceStatisticsUser(HttpUser):
    wait_time = between(0.05, 0.2)

    def on_start(self):
        suffix = uuid.uuid4().hex[:10]
        self.device_identifier = "load-device-" + suffix
        response = self.client.post(
            "/users",
            json={"name": "Load User " + suffix, "email": "load-" + suffix + "@example.com"},
            name="/users",
        )
        response.raise_for_status()
        self.user_id = response.json()["id"]

        response = self.client.post(
            f"/users/{self.user_id}/devices",
            json={"identifier": self.device_identifier},
            name="/users/{user_id}/devices",
        )
        response.raise_for_status()

    @task(10)
    def send_reading(self):
        self.client.post(
            f"/devices/{self.device_identifier}/readings",
            json={
                "x": random.uniform(-100, 100),
                "y": random.uniform(-100, 100),
                "z": random.uniform(-100, 100),
            },
            name="/devices/{device_identifier}/readings",
        )

    @task(2)
    def device_analysis(self):
        self.client.get(
            f"/devices/{self.device_identifier}/analysis",
            name="/devices/{device_identifier}/analysis",
        )

    @task(1)
    def user_analysis(self):
        self.client.get(f"/users/{self.user_id}/analysis", name="/users/{user_id}/analysis")
