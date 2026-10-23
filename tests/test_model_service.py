import io
import unittest
from unittest import mock

from opportunity_radar import model_service


class Settings:
    llm_base_url = "http://127.0.0.1:8080/v1"
    model_autostart = False
    model_start_timeout = 30


class HealthTests(unittest.TestCase):
    def test_ok_payload(self):
        body = io.BytesIO(b'{"status":"ok"}')
        with mock.patch.object(model_service, "urlopen") as opener:
            opener.return_value.__enter__.return_value = body
            self.assertTrue(model_service.health_ok(Settings.llm_base_url))

    def test_bad_payload_is_not_healthy(self):
        body = io.BytesIO(b"<html>no</html>")
        with mock.patch.object(model_service, "urlopen") as opener:
            opener.return_value.__enter__.return_value = body
            self.assertFalse(model_service.health_ok(Settings.llm_base_url))

    def test_connection_error_is_not_healthy(self):
        with mock.patch.object(model_service, "urlopen", side_effect=OSError("down")):
            self.assertFalse(model_service.health_ok(Settings.llm_base_url))


class EnsureTests(unittest.TestCase):
    def test_healthy_model_never_launches_anything(self):
        with mock.patch.object(model_service, "health_ok", return_value=True), \
             mock.patch.object(model_service.subprocess, "Popen") as popen:
            ready, detail = model_service.ensure_model(Settings())
        self.assertTrue(ready)
        self.assertIn("already healthy", detail)
        popen.assert_not_called()

    def test_down_without_autostart_reports_and_does_not_launch(self):
        with mock.patch.object(model_service, "health_ok", return_value=False), \
             mock.patch.object(model_service.subprocess, "Popen") as popen:
            ready, detail = model_service.ensure_model(Settings())
        self.assertFalse(ready)
        self.assertIn("OR_MODEL_AUTOSTART", detail)
        popen.assert_not_called()

    def test_autostart_is_not_attempted_off_windows(self):
        options = Settings()
        options.model_autostart = True
        with mock.patch.object(model_service, "health_ok", return_value=False), \
             mock.patch.object(model_service, "os") as fake_os, \
             mock.patch.object(model_service.subprocess, "Popen") as popen:
            fake_os.name = "posix"
            ready, detail = model_service.ensure_model(options)
        self.assertFalse(ready)
        self.assertIn("Windows", detail)
        popen.assert_not_called()


if __name__ == '__main__':
    unittest.main()
