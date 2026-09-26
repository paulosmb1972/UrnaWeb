# Prompt — Reforma visual da UI do robô mini-dólar

**Objetivo desta reforma:** tornar o layout mais apresentável, profissional, intuitivo e interativo — **sem perder nenhuma funcionalidade, campo, regra de negócio ou comportamento existente**. Isso é um redesenho de apresentação, não uma reescrita de lógica. Qualquer dúvida entre "fica mais bonito" e "risco de quebrar algo que já funciona", a segunda vence.

## 1. CONTEXTO DO SISTEMA

O robô é um sistema de análise técnica automatizada para mini dólar (WDO) com as seguintes camadas:

| Camada | Função |
|---|---|
| Captura de dados | Screenshot de janelas do Profit, RTD via COM, ou ProfitDLL |
| Extração | OCR + IA de visão (OpenRouter/Gemini) lê números do gráfico, SuperDOM, Times & Trades |
| Análise técnica | VWAP, MM9/20/50/200, Bollinger, IFR, Volume Profile, Momentum, Range do dia |
| Gatekeeper | Filtra ENTRADAS (não direção): momentum forte, distância MM9, banda VWAP, fluxo |
| Scoring | Score 0–6 ponderado por agressão, ofertante, regime, horário |
| Macro | PMI, DXY, EWZ, VIX, PTAX, notícias RSS, calendário econômico |
| Decisão | Veredito unificado: direção, convicção, ação (executar/aguardar/monitorar/preparar) |
| Execução | Modo simulação ou real, com alarme sonoro e log de auditoria |

### Ciclo operacional

- Amostragem fixa: 300s (5 min) em todo horário
- Janela operacional: 08:55–18:00
- Persistência: histórico de leituras em disco por ativo
- Atualização: `st_autorefresh` com intervalo dinâmico — **ver a distinção importante na seção 3.2**, o intervalo dinâmico é da tela, não da análise

## 2. ESTRUTURA DE DADOS CENTRAL

Toda a lógica converge para o dicionário `contexto` (retornado por `classificar_contexto`) e o dicionário `registro` (gravado no CSV). O layout DEVE exibir campos destas estruturas.

> **Antes de travar as assinaturas dos helpers (`metric_card()`, `badge()` etc.): faça um diff campo a campo entre as listas abaixo e os dicts reais retornados por `classificar_contexto()` e por `executar_analise()`.** As listas foram levantadas por leitura do código, mas alguns nomes são aproximados — por exemplo, o campo real é `fluxo["exaustao_fluxo"]`, não `fluxo["exaustao"]`. Um nome errado no helper só aparece quebrado em produção, não no teste manual da tela.

### Campos críticos do contexto

```python
contexto = {
    "preco": float,
    "vwap": float,
    "ajuste": float,
    "mm9": float,
    "mm20": float,
    "mm50": float,
    "mm200": float,
    "maxima": float,
    "minima": float,
    "abertura": float,
    "volume": float,
    "regime": str,           # trend_up, trend_down, pullback_up, pullback_down, inconsistente
    "vies": str,             # compra, venda, neutro
    "vies_anterior": str,
    "momentum": dict,        # direcao, forca, inclinacao_mm9, delta_preco, delta_3
    "score": int,            # 0–6
    "score_ponderado": int,
    "score_min": int,
    "acao": str,             # COMPRA, VENDA, ESPERA
    "status_gatilho": str,   # ESPERA, ARMADO, BLOQUEADO
    "execucao_liberada": bool,
    "disparo_auto": bool,
    "engine_status": str,    # APROVADO, ESPERA
    "engine_motivo": str,
    "gatekeeper_status": str,
    "gatekeeper_permitido": bool,
    "veredito": dict,        # direcao, conviccao, acao, fontes
    "veredito_acao": str,    # executar compra, preparar venda, aguardar, etc.
    "rr": float,
    "limiar": float,
    "alvo": float,
    "stop": float,
    "dist_alvo_pts": float,
    "dist_stop_pts": float,
    "estrategia": str,       # Conservador, Agressividade Média
    "conviccao_ponderada": float,
    "pct_acerto": float,
    "pct_perda": float,
    "macro": dict,           # pmi_eua, pmi_vies, dxy, ewz, vix, ptax, noticias
    "faixas": dict,          # verde, amarela, vermelha, ajuste
    "bollinger": dict,       # superior, central, inferior, estado, posicao
    "ifr": dict,             # valor, estado, divergencia
    "vwap_bands": dict,      # vwap, sigma1, sigma2, desvio
    "volume_profile": dict,  # poc, hvn, lvn, modo_estimado (ver nota abaixo)
    "fluxo": dict,           # tendencia, absorcao, exaustao_fluxo, desequilibrio, valido
    "saldo_agressao_pct": float,
    "distancia_maior_ofertante": float,
    "pos_range_dia": float,
    "amplitude_dia": float,
    "atr_dia": float,
    "velocidade_pts_min": float,
    "mudanca_brusca": bool,
    "desc_mudanca_brusca": str,
    "streak_ciclos_neutros": int,
    "escape_neutro_ativo": bool,
    "abertura_observacao": str,
    "abertura_gap_pts": float,
    "abertura_tipo": str,
    "abertura_tendencia": str,
    "padrao_candle": str,
    "volume_candle": float,
    "volume_status": str,
    "volume_financeiro": float,
    "previsao_direcao": str,
    "previsao_prob_alta_5": float,
    "previsao_prob_alta_10": float,
    "rompimento_dispara": bool,
    "rompimento_direcao": str,
    "rompimento_nivel": float,
    "scalp": dict,           # direcao, motivo, vwap_primeiro_toque, ajuste_primeiro_toque
    "zona_exaustao_pts": float,
    "teto_range_compra": float,
    "reversao_extremo": bool,
    "absorcao_favoravel": bool,
    "janela_abertura": bool,
    "momentum_forte": bool,
    "score_saturado": bool,
    "pullback_favoravel": bool,
    "zona_morta": bool,
    "entrada_tardia": bool,
    "corrigido_por_momentum": bool,
    "evento_macro": str,
    "fase_macro": str,
    "minutos_macro": int,
    "macro_vies": str,
    "macro_forca": str,
    "macro_disponivel": bool,
    "macro_parcial": bool,
    "janela_operacional": bool,
    "indices_favor": list,
    "indices_contra": list,
    "ajustes_otimizacao": list,
    "motivo_nao_executavel": str,
    "motivo_bloqueio_simulado": str,
    "auditoria_ia": str,
    "diag": str,
    "conf_visual": str,
    "audio_texto": str,
    "audio_divergente": bool,
    "direcao_correta": str,  # TRUE, FALSE, pendente
    "data_evento": str,
    "data_registro": str,
    "hora_replay_origem": str,
    "versao_motor": str,
    "versao_motor_apelido": str,
    "modo_replay": str,
    "ativo": str,
    "timeframe": str,
    "tipo_painel_lido": str,
    "vwap_origem": str,      # tela, indisponivel
    "fluxo_fonte": str,      # proxy_saldo_agentes
    "tem_nomes_agentes": bool,
    "maior_ofertante_compra": str,
    "maior_ofertante_venda": str,
    "top_compradores": list,
    "top_vendedores": list,
    "estrategia_especial_tipo": str,
    "estrategia_especial_nome": str,
    "lotes_vies": float,
    "lotes_forca": float,
    "lotes_defesa": float,
    "lotes_teto": float,
    "alvo_max_adaptativo": float,
    "alvo_parcial": float,
    "breakeven_em": float,
    "trailing_dist": float,
    "desalavancagem": bool,
}
```

> **Nota — `volume_profile["modo_estimado"]`:** quando nenhum candle da amostra tem volume real capturado, o Volume Profile usa um fallback por TEMPO NO PREÇO (TPO) em vez de ficar indisponível. Quando `modo_estimado=True`, a UI precisa deixar isso visível (ex.: um selo "estimado" no card), senão o operador lê POC/HVN/LVN como volume real negociado quando na verdade é contagem de candles por faixa.

### Campos críticos do registro CSV

Todos os campos acima, mais:

- `DataEvento`, `DataRegistro`, `HoraReplayOrigem`
- `VersaoMotor`, `VersaoMotorApelido`
- `StatusEst`, `VWAP`, `Ajuste`, `PTAX_Tela`, `MM9`, `MM20`, `MM50`, `MM200`
- `PrecoEntrada`, `Abertura`, `Maxima`, `Minima`, `Alvo`, `Stop`
- `PotGanho`, `PotPerda`, `RR`, `PontosFav`, `PontosContra`
- `GatekeeperModo`, `GatekeeperStatus`, `GatekeeperPermitido`
- `ExecucaoLiberada`, `DisparoAuto`
- `EventoMacro`, `FaseMacro`, `MinutosMacro`, `MacroVies`, `MacroForca`
- `PerfilExigeVWAPOk`, `PerfilExigeMM200Ok`, `PerfilPermitePullbackOk`, `PerfilBloqueiaContraTendenciaOk`

## 3. FUNCIONALIDADES DE UI EXISTENTES (PRESERVAR)

### 3.1 Abas principais

O sistema usa `st.tabs` para **5 abas reais** (confirmado no código — `aba_geral, aba_macro, aba_liquidez, aba_candles, aba_confluencia = st.tabs([...])`):

| Aba | Função | Função Python |
|---|---|---|
| Geral | Painel principal com status, score, veredito, diagnóstico | `executar_analise()` renderiza inline |
| Macro | Indicadores macroeconômicos, PMI, DXY, EWZ, VIX, notícias | `veredito_macro_aba()` |
| Liquidez | Book de ofertas, agentes, saldo de agressão, pressão | `veredito_liquidez_aba()` |
| Candles | Análise de padrões de candle, volume, momentum, robô preditivo | `veredito_candles_aba()` |
| Confluência | Síntese dos vereditos das abas anteriores + robô preditivo | `veredito_confluencia_aba()` |

> **Correção importante:** "Config" e "Diagnóstico" **não são abas dedicadas** no código atual — não existem no `st.tabs([...])`. Os controles de configuração (agressividade, ciclo, OpenRouter, fonte de dados) ficam na **sidebar**, e `diagnosticar_janelas_profit()` é chamado de dentro do fluxo existente (sidebar/aba Geral), não de uma aba própria. **Confirme a localização exata no código antes de desenhar em torno dessas seções como se já fossem abas** — se a decisão for promovê-las a abas de verdade, isso é uma funcionalidade NOVA (mudança estrutural), não uma preservação do que já existe, e deve ser tratada como tal no checklist.

### 3.2 Elementos de UI obrigatórios

- **Autorefresh:** `st_autorefresh` com intervalo variável — mais lento fora da janela operacional, mais rápido perto de um evento da agenda macro (`intervalo_refresh_atual()`).
  > **Atenção — isso controla SÓ o re-render da página.** O CICLO DE ANÁLISE de verdade (a chamada de IA que lê a tela e custa créditos) é um mecanismo **separado e sempre fixo em 300s** (`intervalo_analise_atual()`), independente de horário ou evento. Essa separação é proposital: uma versão anterior do sistema confundiu as duas coisas e a IA era chamada quase sem parar, estourando o orçamento de créditos. **O redesenho de UI nunca pode fazer o refresh mais rápido perto de eventos acelerar também o ciclo de análise** — são dois relógios diferentes e devem continuar sendo.
- **Alarme sonoro:** `disparar_alarme()` com beeps e TTS quando gatilho arma ou condição crítica
- **Log de auditoria:** `logger_gatekeeper` + CSV `log_armadilhas_evitadas.csv`
- **Captura de tela:** Preview da imagem analisada pela IA (quando disponível)
- **Status da fonte:** Indicador se está usando RTD, captura de tela, ou fallback
- **Janela operacional:** Alerta quando fora do horário (08:55–18:00)
- **Versão do motor:** Hash automático + apelido visível

### 3.3 Estados do sistema que devem ser visíveis

```
StatusGatilho: ESPERA → ARMADO → BLOQUEADO → (executado)
EngineStatus:  ESPERA → APROVADO
Gatekeeper:    SINAL VALIDADO → [vários bloqueios específicos]
Execucao:      não → sim (quando score ≥ mínimo e gatekeeper libera)
DisparoAuto:   OFF (simulação) → ON (real)
FonteDados:    RTD → Captura → Indisponível
```

## 4. REGRAS DE DESIGN (NÃO QUEBRAR)

### 4.1 Cores semânticas (obrigatórias)

| Estado | Cor | Uso |
|---|---|---|
| Compra / Alta / Aprovado / Favorável | `#10b981` (verde) | Badge OK, execução liberada, tendência de alta |
| Venda / Baixa / Bloqueado / Desfavorável | `#ef4444` (vermelho) | Badge block, execução bloqueada, tendência de baixa |
| Espera / Neutro / Atenção | `#f59e0b` (amarelo) | Badge wait, fora de janela, score baixo |
| Info / Inativo / Simulação | `#3b82f6` (azul) | Modo simulação, dados secundários |
| Texto principal | `#f8fafc` (quase branco) | Títulos, valores |
| Texto secundário | `#8b949e` (cinza) | Labels, timestamps, metadados |
| Fundo | `#0e1117` (dark) | Base do app |
| Superfície | `rgba(22, 27, 34, 0.7)` | Cards, painéis |
| Borda | `#30363d` | Divisórias, contornos |

### 4.2 Tipografia

- Valores numéricos: Monospace (preço, score, RR, percentuais)
- Labels: Sans-serif, caixa alta, letter-spacing leve
- Tamanhos: Label 0.75rem, valor 1.75rem, sub 0.85rem

### 4.3 Layout responsivo

- `layout="wide"` no `st.set_page_config`
- Colunas devem quebrar graciosamente em telas < 1200px
- Cards com min-width para não espremir conteúdo

### 4.4 Performance

- Não bloquear o ciclo de autorefresh com re-renderizações pesadas
- Gráficos devem usar dados em cache (`st.session_state`)
- Imagens de captura devem ser redimensionadas antes de exibir

## 5. NOVAS FUNCIONALIDADES DE UI (ADICIONAR)

### 5.1 Alerta visual de mudança de status

**Trigger:** `StatusGatilho` muda de ESPERA → ARMADO ou ARMADO → BLOQUEADO
**Comportamento:**
- Banner colorido no topo (amarelo para ARMADO, vermelho para BLOQUEADO)
- Dura 1 ciclo de refresh (ou até clicar para dispensar)
- Som de alarme via `disparar_alarme()` já existe — manter

### 5.2 Mini-gráfico de evolução do score

**Dados:** `st.session_state.score_historico` (append a cada ciclo REAL de análise — ver seção 9, nunca a cada rerun do Streamlit — manter últimos 20–50 pontos)
**Visual:** `st.area_chart` nativo do Streamlit
**Linha de referência:** Score mínimo atual (variável por estratégia/horário)
**Cores:** Área verde quando score ≥ mínimo, amarela quando < mínimo, vermelha quando 0

### 5.3 Timeline de eventos do dia

**Dados:** `st.session_state.historico_gatilhos` (append manual ou automático, também só por ciclo real)
**Eventos a registrar:**
- Início do ciclo
- Gatilho ARMADO (com score e RR)
- Gatekeeper bloqueou (com motivo)
- Execução liberada
- Mudança brusca detectada
- Evento macro iniciado/finalizado

**Visual:** Linha do tempo vertical com dots coloridos, hora em monospace, descrição

### 5.4 Indicador de "vida" do sistema

**Elementos:**
- Pulse dot verde: engine processando
- Pulse dot amarelo: aguardando dados RTD/captura
- Pulse dot vermelho piscando: erro crítico ou fonte indisponível
- Contador de registros do dia
- Tempo desde última leitura bem-sucedida

### 5.5 Cards de métricas com contexto

Cada card deve ter:
- Label claro (caixa alta, cinza)
- Valor grande (monospace, cor semântica)
- Subtexto contextual (ex.: "Abaixo do limiar" ou "Favorável se gatilho confirmar")
- Hover sutil (borda mais clara, shadow leve)

### 5.6 Dashboard de regime do dia

**Visual:** Mini gauge ou barra horizontal mostrando:
- % do tempo em trend_up vs trend_down vs pullback vs inconsistente
- Atualizado a cada novo registro

### 5.7 Painel de fonte de dados

Sempre visível no header:
- Ícone + nome da fonte ativa (RTD / Captura / Proxy)
- Status de conexão (conectado / degradado / desconectado)
- Latência da última leitura (ms)
- Botão de fallback manual (forçar captura de tela)

## 6. ESTRUTURA DE ESTADO (`st.session_state`)

Variáveis que devem ser inicializadas e mantidas:

```python
if 'historico_gatilhos' not in st.session_state:
    st.session_state.historico_gatilhos = []
if 'score_historico' not in st.session_state:
    st.session_state.score_historico = []
if 'ultimo_status' not in st.session_state:
    st.session_state.ultimo_status = "ESPERA"
if 'alerta_ativo' not in st.session_state:
    st.session_state.alerta_ativo = False
if 'alerta_mensagem' not in st.session_state:
    st.session_state.alerta_mensagem = ""
if 'registros_hoje' not in st.session_state:
    st.session_state.registros_hoje = 0
if 'ultima_leitura_ok' not in st.session_state:
    st.session_state.ultima_leitura_ok = None  # timestamp
if 'latencia_ms' not in st.session_state:
    st.session_state.latencia_ms = 0
```

## 7. CHECKLIST DE IMPLEMENTAÇÃO

### Fase 1: Estrutura base (sem perder nada)

- [ ] Refatorar CSS em tokens centralizados (dict Python + CSS variables)
- [ ] Criar helpers reutilizáveis: `badge()`, `metric_card()`, `status_item()`
- [ ] Mover todo HTML inline para usar helpers
- [ ] **Verificar a ordem de definição de toda função/helper nova ou movida**: nada pode ser chamado antes de estar definido no fluxo top-to-bottom do script Streamlit — ver anti-padrão na seção 8. Testar rodando o **ciclo automático completo** (`analise_automatica` ligado, deixar rodar sozinho por pelo menos 2-3 ciclos de 5 min), não só abrir a tela manualmente e clicar no botão.
- [ ] **Conferir campo a campo** os dicts reais de `contexto` (retorno de `classificar_contexto`) e `registro` (retorno de `executar_analise`) contra as listas da seção 2 antes de travar as assinaturas dos helpers
- [ ] Garantir que `executar_analise()` continua retornando o mesmo `registro`
- [ ] Garantir que CSV é gravado com os mesmos campos

### Fase 2: Novos elementos

- [ ] Implementar `detectar_mudanca_status()` com alerta visual
- [ ] Implementar `score_historico` com append a cada ciclo real
- [ ] Implementar `historico_gatilhos` com eventos chave
- [ ] Adicionar mini-gráfico de score
- [ ] Adicionar timeline de eventos
- [ ] Adicionar indicadores de pulso (vida do sistema)

### Fase 3: Polimento

- [ ] Testar responsividade em 1366×768 e 1920×1080
- [ ] Verificar que alarmes sonoros ainda funcionam
- [ ] Verificar que autorefresh não quebra com novos elementos, e que o ciclo de análise continua fixo em 300s independente do refresh visual
- [ ] Validar que modo replay continua funcionando
- [ ] Validar que exportação CSV não muda formato

## 8. ANTI-PADRÕES (EVITAR)

| Não fazer | Por quê |
|---|---|
| Mover funções/helpers para depois do primeiro ponto do script que os chama | Streamlit executa o arquivo de cima a baixo a cada rerun — uma função usada ANTES de estar definida quebra com `NameError`. Já aconteceu em produção neste projeto: o ciclo automático ficou horas sem rodar, falhando em silêncio, até ser diagnosticado. Qualquer refatoração estrutural (tokens de CSS, helpers, mover código) precisa ser testada no ciclo automático completo, não só abrindo a tela manualmente |
| Quebrar `executar_analise()` em funções menores sem manter retorno | O CSV e o log dependem do dict `registro` exato |
| Mudar nome de campo no CSV | Quebra análise histórica e replay |
| Usar `st.cache_data` para dados mutáveis de sessão | Use `st.session_state` |
| Bloquear thread principal com gráficos pesados | Streamlit roda em single thread |
| Remover `st_autorefresh` | O ciclo de 5 min é regra de negócio |
| Fazer o refresh de tela mais rápido (perto de evento) acelerar também o ciclo de análise | São dois mecanismos separados de propósito — confundi-los já causou consumo excessivo de créditos de IA no passado (ver seção 3.2) |
| Ignorar `modo_replay` | O sistema é validado principalmente via replay |
| Mudar cores semânticas | O operador associa verde=compra, vermelho=venda |
| Remover preview da imagem capturada | É a única forma de auditar erros de IA |

## 9. EXEMPLO DE INTEGRAÇÃO

```python
# No final de executar_analise(), após montar 'registro':
# (isso só roda uma vez por CICLO REAL de análise, nunca por rerun/clique
# de widget — mesma regra que já protege o histórico de leituras do book)

# 1. Atualiza histórico de score
st.session_state.score_historico.append({
    "hora": registro["DataEvento"].split()[-1][:5],
    "score": registro["Score"],
    "status": registro["StatusGatilho"]
})
st.session_state.score_historico = st.session_state.score_historico[-50:]

# 2. Detecta mudança de status
if registro["StatusGatilho"] != st.session_state.ultimo_status:
    st.session_state.alerta_ativo = True
    st.session_state.alerta_mensagem = (
        f"Status: {st.session_state.ultimo_status} → {registro['StatusGatilho']}"
    )
    # Dispara som se necessário
    if registro["StatusGatilho"] == "ARMADO":
        disparar_alarme("Gatilho armado!", tipo="alerta")
st.session_state.ultimo_status = registro["StatusGatilho"]

# 3. Registra evento na timeline
if registro["StatusGatilho"] in ("ARMADO", "BLOQUEADO"):
    st.session_state.historico_gatilhos.append({
        "hora": registro["DataEvento"].split()[-1][:5],
        "evento": f"{registro['StatusGatilho']} — Score {registro['Score']}/{registro['ScoreMin']}, RR {registro['RR']}",
        "tipo": registro["StatusGatilho"].lower()
    })

# 4. Incrementa contador
st.session_state.registros_hoje += 1
st.session_state.ultima_leitura_ok = datetime.now()
```

## 10. MÉTRICAS DE SUCESSO

Após implementação, o novo layout deve manter:

- **Zero regressão funcional:** todo ciclo de análise produz o mesmo CSV
- **Latência ≤ 2s adicional por ciclo** (medido vs baseline)
- **Tempo de scan do operador ≤ 3s** para entender estado atual
- **100% dos campos críticos visíveis sem scroll** em 1920×1080
- **Alarmes sonoros preservados** para ARMADO e erro crítico
- **Ciclo de análise continua fixo em 300s**, independente de qualquer mudança no refresh visual (ver seção 3.2 e 8)
