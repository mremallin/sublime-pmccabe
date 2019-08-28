import sublime
import sublime_plugin

import os
from subprocess import Popen, PIPE

class PmccabeCommand(sublime_plugin.WindowCommand):
    def _get_pmccabe_executable(self):
        s = sublime.load_settings("Preferences.sublime-settings")
        pmccabe_executable = s.get("pmccabe_executable", "/usr/bin/pmccabe")
        return pmccabe_executable

    def run(self):
        view = self.window.active_view()
        code_text = view.substr(sublime.Region(0, view.size()))

        self.output_panel = self.window.create_output_panel("pmccabe")
        self.window.run_command("show_panel", {"panel": "output.pmccabe"})

        p = Popen([self._get_pmccabe_executable()], stdout=PIPE, stdin=PIPE, stderr=PIPE,
                  universal_newlines=True)
        pmccabe_stdout = p.communicate(input=code_text)[0]
        self.output_panel.run_command('append', 
            {'characters': pmccabe_stdout, 'force': True, 'scroll_to_end': True})
        sublime.log(pmccabe_stdout)

    def is_enabled(self):
        pmccabe_executable = self._get_pmccabe_executable()
        if not os.path.exists(pmccabe_executable):
            sublime.error_message("The pmccabe executable provided at '{}' does not exist".format(pmccabe_executable))
            return False

        return True
