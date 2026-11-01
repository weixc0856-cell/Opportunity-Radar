"""Static checks on the Windows launcher and task installer.

These two scripts cannot be executed by a test - running run-digest.ps1 would start a real
digest and send mail - so the checks are on the text that decides the operational behaviour:
the power settings that stopped the task on 2026-10-29 and 2026-11-01, the Interactive logon
that must not be changed as a side effect, and the exit records that make a terminated
launcher distinguishable from a failed CLI.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / 'deploy' / 'windows' / 'install-task.ps1'
RUN = ROOT / 'deploy' / 'windows' / 'run-digest.ps1'


def text_of(path):
    return path.read_text(encoding='utf-8')


class InstallTaskTests(unittest.TestCase):
    def settings_call(self):
        """The New-ScheduledTaskSettingsSet invocation, including its continuation lines."""
        text = text_of(INSTALL)
        start = text.index('New-ScheduledTaskSettingsSet')
        return text[start:start + 400]

    def test_battery_switches_are_set_on_the_settings_object(self):
        call = self.settings_call()
        self.assertIn('-DontStopIfGoingOnBatteries', call)
        self.assertIn('-AllowStartIfOnBatteries', call)

    def test_execution_time_limit_is_still_declared(self):
        self.assertIn('-ExecutionTimeLimit', self.settings_call())

    def test_logon_identity_is_not_changed(self):
        text = text_of(INSTALL)
        for flag in ('-User ', '-Password', '-RunLevel', '-Principal'):
            self.assertNotIn(flag, text, 'changing the logon identity is a separate decision')

    def test_the_registered_object_is_read_back(self):
        text = text_of(INSTALL)
        self.assertIn('Get-ScheduledTask -TaskName $TaskName', text)
        self.assertIn('StopIfGoingOnBatteries', text,
                      'the installer must report what the task actually registered')

    def test_the_action_is_unchanged(self):
        text = text_of(INSTALL)
        self.assertIn('run-digest.ps1', text)
        self.assertIn('Register-ScheduledTask', text)


class RunDigestTests(unittest.TestCase):
    def test_every_phase_is_recorded(self):
        text = text_of(RUN)
        for marker in ('Starting Opportunity Radar (run',
                       'start-model',
                       'CLI starting:',
                       'CLI started (pid',
                       'CLI exit code',
                       'Finished Opportunity Radar with exit code'):
            self.assertIn(marker, text, marker)

    def test_a_terminated_launcher_is_detectable(self):
        text = text_of(RUN)
        self.assertIn('launcher-inflight.json', text)
        self.assertIn('WARNING: previous launcher left an unfinished run marker', text)
        self.assertIn('Remove-Item -Path $markerPath', text,
                      'a completed run must clear the marker')

    def test_the_child_pid_is_written_before_waiting(self):
        text = text_of(RUN)
        marker_write = text.index('"cli_pid":')
        wait = text.index('$proc.WaitForExit()')
        self.assertLess(marker_write, wait,
                        'a terminated launcher must leave the pid of the process it left behind')

    def test_an_unknown_exit_code_is_a_failure(self):
        text = text_of(RUN)
        self.assertIn('$null -eq $proc.ExitCode', text)
        self.assertIn('recorded as failed', text)

    def test_the_exit_code_is_actually_tracked(self):
        # PowerShell 5.1 returns an empty ExitCode on a -PassThru object unless the exit
        # event is enabled; without this line every run would report success.
        self.assertIn('EnableRaisingEvents = $true', text_of(RUN))

    def test_no_early_exit_skips_the_finally_block(self):
        text = text_of(RUN)
        body = text[text.index('try {'):text.index('finally {')]
        statements = re.findall(r'(?m)^\s*exit\b', body)
        self.assertEqual(statements, [], 'an exit statement inside try would skip the finally block')
        self.assertRegex(text, r'\$code = 1', 'the exit code must start as a failure')

    def test_the_business_steps_are_unchanged(self):
        """The launcher must still do the same three things in the same order."""
        text = text_of(RUN)
        order = [text.index('docker compose up -d'),
                 text.index('start-model.ps1'),
                 text.index("'opportunity_radar.cli'")]
        self.assertEqual(order, sorted(order))


if __name__ == '__main__':
    unittest.main()
