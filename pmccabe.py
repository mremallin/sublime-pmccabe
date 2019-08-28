import sublime
import sublime_plugin

import os

class PmccabeCommand(sublime_plugin.WindowCommand):
    def run(self):
        view = self.window.active_view()
        code_text = view.substr(sublime.Region(0, view.size()))

        output_panel = self.window.create_output_panel("pmccabe")
        self.window.run_command("show_panel", {"panel": "output.pmccabe"})

    def is_enabled(self):
        s = sublime.load_settings("Preferences.sublime-settings")
        pmccabe_executable = s.get("pmccabe_executable", "/usr/bin/pmccabe")
        if not os.path.exists(pmccabe_executable):
            sublime.error_message("The pmccabe executable provided at '{}' does not exist".format(pmccabe_executable))
            return False

        return True
