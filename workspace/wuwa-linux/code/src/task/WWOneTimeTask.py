from src.platform_io import desktop_cursor_available
from src.task.MouseResetTask import MouseResetTask


class WWOneTimeTask:

    def run(self):
        mouse_reset_task = self.executor.get_task_by_class(MouseResetTask)
        mouse_reset_task.run()
        if desktop_cursor_available() and not self.is_browser():
            from ok import PostMessageInteraction
            if isinstance(self.executor.interaction, PostMessageInteraction):
                self.executor.interaction.activate()
        self.sleep(0.5)
