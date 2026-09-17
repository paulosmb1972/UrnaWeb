"""Ambiente minimo para testar a engine de decisao de robo_mini_dolar.py
sem Streamlit real nem as dependencias Windows-only (pywin32, pygetwindow).

robo_mini_dolar.py e um script Streamlit executado de cima a baixo (sem
`if __name__ == "__main__"`), entao nao da para importa-lo normalmente.
Este modulo cria stubs minimos para as bibliotecas de plataforma e para o
`streamlit` (com um `session_state` de verdade, dict-like), executa o
arquivo uma unica vez com `exec()` e devolve o namespace resultante — dali
os testes chamam as funcoes da engine (`_detectar_indicadores`,
`avaliar_conviccao`, `liberar_tendencia_forte_sem_pullback`, etc.)
diretamente, com dados sinteticos.
"""
import os
import sys
import types

_ROBO_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "robo_mini_dolar.py")


class Ghost:
    """Objeto camaleao: qualquer atributo/chamada devolve outro Ghost.
    Usado para stubar widgets do Streamlit (st.button, st.columns, ...)
    sem precisar modelar a API inteira."""
    def __call__(self, *a, **k):
        return Ghost()

    def __getattr__(self, name):
        return Ghost()

    def __enter__(self):
        return Ghost()

    def __exit__(self, *a):
        return False

    def __iter__(self):
        return iter([Ghost() for _ in range(12)])

    def __bool__(self):
        return False

    def __getitem__(self, k):
        return Ghost()

    def __setitem__(self, k, v):
        pass

    def __len__(self):
        return 0

    def __float__(self):
        return 0.0

    def __str__(self):
        return ""


def _stub_module(name):
    mod = types.ModuleType(name)
    mod.__getattr__ = lambda n: Ghost()
    return mod


class FakeSessionState(dict):
    """st.session_state de verdade suporta atributo E item (session_state.x
    == session_state["x"]) — o app usa as duas formas o tempo todo."""
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)

    def __setattr__(self, name, value):
        self[name] = value


class FakeStreamlit(Ghost):
    def __init__(self):
        self.session_state = FakeSessionState()

    def columns(self, spec=2, **k):
        try:
            n = len(spec)
        except TypeError:
            n = int(spec)
        return tuple(Ghost() for _ in range(n))

    def tabs(self, labels, **k):
        return tuple(Ghost() for _ in labels)

    def cache_data(self, *a, **k):
        if a and callable(a[0]) and not k:
            return a[0]
        return lambda f: f

    def cache_resource(self, *a, **k):
        if a and callable(a[0]) and not k:
            return a[0]
        return lambda f: f

    def button(self, *a, **k):
        return False

    def toggle(self, *a, **k):
        return k.get("value", False)

    def selectbox(self, label, options, *a, **k):
        try:
            return options[k.get("index", 0) or 0]
        except Exception:
            return None

    def set_page_config(self, *a, **k):
        pass


def carregar_engine():
    """Executa robo_mini_dolar.py num namespace isolado, com streamlit e as
    libs Windows-only mockadas, e devolve (namespace, fake_st).

    Chame uma vez por processo de teste (setUpModule) — reexecutar o
    arquivo inteiro a cada teste seria lento e desnecessario, ja que as
    funcoes da engine sao puras o suficiente (leem/gravam so
    st.session_state, que cada teste pode resetar)."""
    for name in ("pygetwindow", "win32api", "win32gui", "win32ui", "win32con", "winsound",
                 "pythoncom", "yfinance"):
        sys.modules[name] = _stub_module(name)
    _w32_client = _stub_module("win32com.client")
    sys.modules["win32com.client"] = _w32_client
    _w32 = _stub_module("win32com")
    _w32.client = _w32_client
    sys.modules["win32com"] = _w32

    _autorefresh = types.ModuleType("streamlit_autorefresh")
    _autorefresh.st_autorefresh = lambda *a, **k: 0
    sys.modules["streamlit_autorefresh"] = _autorefresh

    fake_st = FakeStreamlit()
    st_mod = types.ModuleType("streamlit")
    for attr in dir(fake_st):
        if not attr.startswith("__"):
            try:
                setattr(st_mod, attr, getattr(fake_st, attr))
            except Exception:
                pass
    st_mod.session_state = fake_st.session_state
    st_mod.__getattr__ = lambda n: Ghost()
    sys.modules["streamlit"] = st_mod

    with open(_ROBO_PATH, encoding="utf-8") as f:
        source = f.read()

    namespace = {"__name__": "robo_mini_dolar_under_test", "__file__": _ROBO_PATH}
    exec(compile(source, _ROBO_PATH, "exec"), namespace)
    return namespace, fake_st
