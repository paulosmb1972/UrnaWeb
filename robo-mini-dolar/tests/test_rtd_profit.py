"""Testes do modulo rtd_profit.

Rodam em qualquer SO — o servidor RTD (COM/Windows) e substituido por um
duble. Testam a logica que realmente pode quebrar em producao: conversao de
numeros vindos do RTD, agregacao de candles, calculo de indicadores e
degradacao segura quando o Profit esta fechado.

Rodar:  python3 -m unittest tests.test_rtd_profit -v
"""
import os
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rtd_profit import (  # noqa: E402
    AgregadorCandles, FonteDadosRTD, LeitorRTD, _num,
)


class TestConversaoNumerica(unittest.TestCase):
    """_num precisa engolir tudo que o RTD devolve sem quebrar o ciclo."""

    def test_numeros_normais(self):
        self.assertEqual(_num(5120.5), 5120.5)
        self.assertEqual(_num("5120.5"), 5120.5)
        self.assertEqual(_num(5120), 5120.0)

    def test_virgula_decimal(self):
        self.assertEqual(_num("5120,50"), 5120.5)

    def test_mensagens_de_erro_do_rtd_viram_zero(self):
        # Erros reais documentados pela Nelogica.
        for erro in ["#N/D", "RTD Desativado", "Ferramenta Invalida",
                     "Atributo Invalido", "A janela foi fechada", "", None]:
            self.assertEqual(_num(erro), 0.0, f"deveria virar 0.0: {erro!r}")

    def test_nan_vira_zero(self):
        self.assertEqual(_num(float("nan")), 0.0)


class TestAgregadorCandles(unittest.TestCase):

    def setUp(self):
        self.ag = AgregadorCandles(timeframe_min=10)
        self.t0 = datetime(2026, 9, 14, 10, 0, 0)

    def test_agrupa_no_mesmo_bucket(self):
        self.ag.registrar(5120.0, quando=self.t0)
        self.ag.registrar(5125.0, quando=self.t0 + timedelta(minutes=3))
        self.ag.registrar(5118.0, quando=self.t0 + timedelta(minutes=9))
        self.assertEqual(len(self.ag.candles), 1, "9 min no TF de 10 = mesmo candle")
        c = self.ag.candles[-1]
        self.assertEqual(c.abertura, 5120.0)
        self.assertEqual(c.maxima, 5125.0)
        self.assertEqual(c.minima, 5118.0)
        self.assertEqual(c.fechamento, 5118.0)

    def test_abre_candle_novo_ao_virar_bucket(self):
        self.ag.registrar(5120.0, quando=self.t0)
        self.ag.registrar(5130.0, quando=self.t0 + timedelta(minutes=11))
        self.assertEqual(len(self.ag.candles), 2)

    def test_volume_acumulado_vira_incremento(self):
        """O RTD entrega volume ACUMULADO do dia — o candle quer o delta."""
        self.ag.registrar(5120.0, volume_acumulado=1000, quando=self.t0)
        self.ag.registrar(5121.0, volume_acumulado=1500, quando=self.t0 + timedelta(minutes=1))
        self.assertEqual(self.ag.candles[-1].volume, 1500.0,
                          "primeiro tick (1000) + incremento (500)")

    def test_virada_de_dia_nao_gera_volume_negativo(self):
        self.ag.registrar(5120.0, volume_acumulado=9000, quando=self.t0)
        self.ag.registrar(5121.0, volume_acumulado=200,
                          quando=self.t0 + timedelta(minutes=11))
        self.assertGreaterEqual(self.ag.candles[-1].volume, 0.0)

    def test_preco_invalido_e_ignorado(self):
        self.ag.registrar(0.0, quando=self.t0)
        self.ag.registrar(-5.0, quando=self.t0)
        self.assertEqual(len(self.ag.candles), 0)


class TestIndicadoresCalculados(unittest.TestCase):

    def setUp(self):
        self.ag = AgregadorCandles(timeframe_min=10)
        t = datetime(2026, 9, 14, 9, 0, 0)
        # 30 candles subindo 1 ponto por candle: 5100, 5101, ... 5129
        for i in range(30):
            self.ag.registrar(5100.0 + i, volume_acumulado=(i + 1) * 100,
                              quando=t + timedelta(minutes=10 * i))

    def test_media_movel_9(self):
        # ultimos 9 fechamentos: 5121..5129 -> media 5125
        self.assertEqual(self.ag.media_movel(9), 5125.0)

    def test_media_movel_sem_amostra_devolve_zero(self):
        self.assertEqual(self.ag.media_movel(200), 0.0,
                          "MM200 sem 200 candles tem que ser 0, nao um numero inventado")

    def test_vwap_ponderada_por_volume(self):
        vwap = self.ag.vwap_sessao()
        self.assertGreater(vwap, 5100.0)
        self.assertLess(vwap, 5130.0)

    def test_atr_positivo(self):
        self.assertGreater(self.ag.atr(), 0.0)

    def test_hist_candles_mais_recente_primeiro(self):
        h = self.ag.para_hist_candles()
        self.assertEqual(h[0]["fechamento"], 5129.0, "app espera o mais recente no indice 0")
        self.assertEqual(h[-1]["fechamento"], 5100.0)

    def test_semear_historico_habilita_mm50(self):
        ag = AgregadorCandles(timeframe_min=10)
        hist = [{"abertura": 5000.0 + i, "maxima": 5002.0 + i, "minima": 4998.0 + i,
                 "fechamento": 5000.0 + i, "volume": 100} for i in range(60)]
        aceitos = ag.semear_historico(hist)
        self.assertEqual(aceitos, 60)
        self.assertGreater(ag.media_movel(50), 0.0,
                            "com historico semeado a MM50 passa a existir")

    def test_semear_historico_descarta_candle_invalido(self):
        ag = AgregadorCandles()
        ruim = [{"abertura": 0, "maxima": 0, "minima": 0, "fechamento": 0}]
        self.assertEqual(ag.semear_historico(ruim), 0)


# ---------------------------------------------------------------------------
# Dubles do servidor RTD (COM)
# ---------------------------------------------------------------------------

class _ServidorRTDFalso:
    """Imita IRtdServer: ServerStart/ConnectData/RefreshData/DisconnectData."""

    def __init__(self, valores, server_start=1):
        self.valores = valores          # {atributo: valor}
        self._server_start = server_start
        self.topicos = {}               # tid -> atributo
        self.terminado = False

    def ServerStart(self, callback):
        return self._server_start

    def ConnectData(self, tid, strings, get_new):
        self.topicos[tid] = strings[1]
        return self.valores.get(strings[1], 0.0)

    def RefreshData(self, count):
        tids = sorted(self.topicos)
        linha_ids = [float(t) for t in tids]
        linha_val = [self.valores.get(self.topicos[t], 0.0) for t in tids]
        return len(tids), [linha_ids, linha_val]

    def DisconnectData(self, tid):
        self.topicos.pop(tid, None)

    def ServerTerminate(self):
        self.terminado = True


def _conectar_com_duble(leitor, servidor):
    """Injeta o servidor falso sem passar pelo COM real."""
    leitor._servidor = servidor
    for nome, attr in leitor.atributos.items():
        tid = leitor._proximo_topico
        leitor._proximo_topico += 1
        servidor.ConnectData(tid, [leitor.ticker_rtd, attr], True)
        leitor._topicos[tid] = nome
    leitor.conectado = True
    return leitor


class TestLeitorRTD(unittest.TestCase):

    def test_ticker_formato_bmf(self):
        self.assertEqual(LeitorRTD("WDOV26").ticker_rtd, "WDOV26_F_0")
        self.assertEqual(LeitorRTD("wdov26").ticker_rtd, "WDOV26_F_0",
                          "ticker tem que ser normalizado para maiusculo")

    def test_leitura_normal(self):
        leitor = LeitorRTD("WDOV26")
        srv = _ServidorRTDFalso({"ULT": 5122.5, "ABE": 5117.5, "MAX": 5129.0,
                                  "MIN": 5121.5, "AJA": 5134.44, "VOL": 12000})
        _conectar_com_duble(leitor, srv)
        d = leitor.ler()
        self.assertTrue(d["conectado"])
        self.assertEqual(d["ultimo"], 5122.5)
        self.assertEqual(d["maxima"], 5129.0)
        self.assertEqual(d["ajuste_ant"], 5134.44)

    def test_sem_conectar_devolve_estrutura_segura(self):
        """Profit fechado: nunca lanca excecao, nunca devolve numero inventado."""
        d = LeitorRTD("WDOV26").ler()
        self.assertFalse(d["conectado"])
        self.assertEqual(d["ultimo"], 0.0)
        self.assertIn("erro", d)

    def test_refresh_com_erro_nao_lanca_excecao(self):
        leitor = LeitorRTD("WDOV26")

        class Explosivo(_ServidorRTDFalso):
            def RefreshData(self, count):
                raise RuntimeError("RTD caiu")

        _conectar_com_duble(leitor, Explosivo({}))
        d = leitor.ler()
        self.assertIn("RefreshData falhou", d["erro"])

    def test_valores_de_erro_do_rtd_nao_viram_preco(self):
        """'#N/D' na celula nao pode virar preco — tem que zerar."""
        leitor = LeitorRTD("WDOV26")
        _conectar_com_duble(leitor, _ServidorRTDFalso({"ULT": "#N/D", "MAX": "RTD Desativado"}))
        d = leitor.ler()
        self.assertEqual(d["ultimo"], 0.0)
        self.assertEqual(d["maxima"], 0.0)


class TestFonteDadosRTD(unittest.TestCase):
    """A fachada precisa entregar exatamente os campos que a captura visual
    vinha falhando (OHLC, volume, ajuste, vwap, medias)."""

    def _fonte(self, valores):
        f = FonteDadosRTD("WDOV26", timeframe_min=10)
        _conectar_com_duble(f.leitor, _ServidorRTDFalso(valores))
        return f

    def test_preenche_campos_que_faltavam(self):
        f = self._fonte({"ULT": 5122.5, "ABE": 5117.5, "MAX": 5129.0,
                          "MIN": 5121.5, "AJA": 5134.44, "VOL": 8000})
        d = f.ler_dados_tela()
        # Os campos com 10%-41% de leitura na captura visual:
        self.assertEqual(d["preco_atual"], 5122.5)
        self.assertEqual(d["abertura"], 5117.5)
        self.assertEqual(d["maxima"], 5129.0)
        self.assertEqual(d["minima"], 5121.5)
        self.assertEqual(d["ajuste"], 5134.44)
        # Volume do candle: 0% de leitura na captura visual.
        self.assertGreater(d["volume"], 0.0)
        self.assertTrue(d["rtd_conectado"])
        self.assertEqual(d["fonte_dados"], "rtd")

    def test_vwap_calculada_nao_lida(self):
        """A captura visual chegou a reportar 'VWAP Band 5196,70' com preco em
        5124,50. Aqui a VWAP e calculada do proprio fluxo — nao ha como ler o
        indicador errado."""
        f = self._fonte({"ULT": 5122.5, "VOL": 1000})
        d = f.ler_dados_tela()
        self.assertEqual(d["vwap"], 5122.5, "com um unico tick, VWAP = o proprio preco")
        self.assertEqual(d["vwap_origem"], "calculado_rtd")

    def test_medias_longas_zeram_sem_historico(self):
        """Sem semear historico, MM50/MM200 devem ser 0 — nunca um valor
        inventado a partir de 1 candle."""
        f = self._fonte({"ULT": 5122.5})
        d = f.ler_dados_tela()
        self.assertEqual(d["mm50"], 0.0)
        self.assertEqual(d["mm200"], 0.0)

    def test_profit_fechado_degrada_sem_quebrar(self):
        f = FonteDadosRTD("WDOV26")  # nunca conectou
        d = f.ler_dados_tela()
        self.assertFalse(d["rtd_conectado"])
        self.assertEqual(d["preco_atual"], 0.0)
        self.assertEqual(d["fonte_dados"], "rtd_indisponivel")
        self.assertEqual(d["vwap_origem"], "indisponivel")

    def test_hist_candles_no_formato_do_app(self):
        f = self._fonte({"ULT": 5122.5, "VOL": 500})
        f.ler_dados_tela()
        h = f.hist_candles()
        self.assertTrue(h)
        for chave in ("abertura", "maxima", "minima", "fechamento", "volume"):
            self.assertIn(chave, h[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
