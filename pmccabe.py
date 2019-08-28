import sublime
import sublime_plugin

import os

class PmccabeCommand(sublime_plugin.WindowCommand):
    def run(self):
        view = self.view
        code_text = view.substr(0, view.size())

    def is_enabled(self):
        s = sublime.load_settings("Preferences.sublime-settings")
        pmccabe_executable = s.get("pmccabe_executable", "/usr/bin/pmccabe")
        if not os.path.exists(pmccabe_executable):
            sublime.error_message("The pmccabe executable provided at '{}' does not exist".format(pmccabe_executable))
            return False

        return True
