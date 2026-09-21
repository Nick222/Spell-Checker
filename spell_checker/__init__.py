from pathlib import Path
import re

from gi.repository import Gtk

from zim.plugins import PluginClass
from zim.actions import action
from zim.gui.mainwindow import MainWindowExtension
from zim.newfs import LocalFile

import enchant


class SpellCheckerPlugin(PluginClass):

    plugin_info = {
        'name': 'Spell Checker',
        'description': 'Check spelling in notebook pages',
        'author': 'Nick',
    }


class SpellCheckerMainWindowExtension(MainWindowExtension):

    def __init__(self, plugin, window):
        super().__init__(plugin, window)

        self.check_window = None
        self.model = None

    @action('Проверка орфографии', menuhints='tools')
    def spell_check(self):

        if self.check_window is not None:
            self.check_window.present()
            return

        self.check_window = Gtk.Window(
            title='Проверка орфографии'
        )

        self.check_window.set_default_size(
            900,
            600
        )

        self.check_window.set_position(
            Gtk.WindowPosition.CENTER
        )

        self.check_window.connect(
            'destroy',
            self._on_window_destroy
        )

        vbox = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=6
        )

        vbox.set_border_width(10)

        self.check_window.add(vbox)

        # -------------------------------------------------
        # Controls
        # -------------------------------------------------

        button = Gtk.Button(
            label='Проверить'
        )

        button.connect(
            'clicked',
            self._check_notebook
        )

        vbox.pack_start(
            button,
            False,
            False,
            0
        )

        # -------------------------------------------------
        # Results
        # -------------------------------------------------

        self.model = Gtk.ListStore(
            str,     # 0 page
            int,     # 1 line
            str,     # 2 word
            str,     # 3 suggestions
            str,     # 4 filename
        )

        self.tree = Gtk.TreeView(
            model=self.model
        )

        self.tree.set_headers_visible(True)

        self._add_column(
            'Заметка',
            0,
            expand=True
        )

        self._add_column(
            'Строка',
            1
        )

        self._add_column(
            'Ошибка',
            2
        )

        self._add_column(
            'Варианты',
            3,
            expand=True
        )

        self.tree.connect(
            'row-activated',
            self._row_activated
        )

        scroll = Gtk.ScrolledWindow()

        scroll.set_policy(
            Gtk.PolicyType.AUTOMATIC,
            Gtk.PolicyType.AUTOMATIC
        )

        scroll.add(self.tree)

        vbox.pack_start(
            scroll,
            True,
            True,
            0
        )

        self.check_window.show_all()

    # =====================================================
    # Columns
    # =====================================================

    def _add_column(
        self,
        title,
        index,
        expand=False
    ):

        renderer = Gtk.CellRendererText()

        column = Gtk.TreeViewColumn(
            title,
            renderer,
            text=index
        )

        if expand:
            column.set_expand(True)

        self.tree.append_column(column)

    # =====================================================
    # Check notebook
    # =====================================================

    def _check_notebook(self, button):

        self.model.clear()

        dictionary = enchant.Dict(
            'ru_RU'
        )

        root = Path(
            self.window.notebook.folder.path
        )

        for filename in root.rglob('*.txt'):

            self._check_file(
                filename,
                dictionary
            )

    # =====================================================
    # Check one file
    # =====================================================

    def _check_file(
        self,
        filename,
        dictionary
    ):

        try:

            text = filename.read_text(
                encoding='utf-8'
            )

        except Exception:
            return

        lines = text.splitlines()

        for line_number, line in enumerate(
            lines[4:],
            start=5
        ):

            # Заголовки
            if re.search(
                r'={2,}',
                line
            ):
                continue

            # Убираем ссылки [[...]]
            line = re.sub(
                r'\[\[.*?\]\]',
                ' ',
                line
            )

            # Проверяем слова
            words = re.findall(
                r"[A-Za-zА-Яа-яЁё]+(?:[-'][A-Za-zА-Яа-яЁё]+)*",
                line
            )

            for word in words:

                if dictionary.check(word):
                    continue

                suggestions = dictionary.suggest(
                    word
                )

                suggestions_text = ', '.join(
                    suggestions[:5]
                )

                page = filename.stem

                self.model.append(
                    [
                        page,
                        line_number,
                        word,
                        suggestions_text,
                        str(filename),
                    ]
                )

    # =====================================================
    # Open result
    # =====================================================

    def _row_activated(
        self,
        tree,
        path,
        column
    ):

        model = tree.get_model()

        row = model[path]

        filename = row[4]

        try:

            file = LocalFile(
                filename
            )

            page_path, file_type = (
                self.window.notebook.layout.map_file(
                    file
                )
            )

            page = (
                self.window.notebook.get_page(
                    page_path
                )
            )

            self.window.pageview.set_page(
                page
            )

        except Exception as error:

            dialog = Gtk.MessageDialog(
                transient_for=self.check_window,
                flags=Gtk.DialogFlags.MODAL,
                message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.OK,
                text='Не удалось открыть заметку'
            )

            dialog.format_secondary_text(
                str(error)
            )

            dialog.run()
            dialog.destroy()

    # =====================================================
    # Window
    # =====================================================

    def _on_window_destroy(self, window):

        self.check_window = None