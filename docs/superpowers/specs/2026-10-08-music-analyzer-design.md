# music-analyzer — design

Data: 2026-10-08

## Objetivo

Extrair do Spotaste só a análise musical para um repositório próprio, pequeno e numa linguagem só, que sirva de referência para um site (construído com o GPT) incorporar ou adaptar. O site recebe a lista de músicas do Spotify de cada pessoa; este repositório mostra como transformar essa lista em features de áudio e letra por música.

Critério de sucesso: com `docker compose up` e um comando, um export do Spotify vira um arquivo de resultados em que cada música tem features de áudio e letra, e os valores de áudio batem com os que o Spotaste já produz.

## Fora do escopo

- Autenticação e fila multiusuário (o site desenha isso do jeito dele).
- Extração de temas ou idioma da letra (fica com o GPT).
- Login Spotify, roast, playlists, matcher, frontend.
- Mudanças no repositório `spotaste-monorep`.

## Estrutura

```
analyzer/
  app.py              # Flask: POST /analyze, GET /health
  audio.py            # download (yt-dlp) + features (Essentia) + moods (8 modelos MusiCNN)
  lyrics.py           # LRCLIB → lyrics.ovh, limpeza de nomes, checagem de artista
  meta.py             # índice das classes dos modelos e categorias de erro (sem dependência pesada)
  download_models.py  # baixa os modelos na build
batch/
  history.py          # leitura do export do Spotify → ranking de faixas (funções puras)
  store.py            # resultados em SQLite
  import_history.py   # CLI que liga history → /analyze → store
tests/
Dockerfile
docker-compose.yml
requirements.txt        # do container
requirements-dev.txt    # pytest, requests (batch e testes rodam fora do container)
README.md
```

`analyzer/` roda dentro do container (precisa de Essentia, que só tem wheel linux x86_64). `batch/` e `tests/` rodam no host com Python 3.11+ e só dependem de `requests` e `pytest`.

## Serviço (`analyzer/`)

### `POST /analyze`

Entrada: `{"track": "...", "artist": "..."}`. Falta de campo → 400.

Saída, sempre 200 quando a entrada é válida:

```json
{
  "track": "Sweater Weather",
  "artist": "The Neighbourhood",
  "audio": {
    "bpm": 123.8, "key": "Bb", "mode": "major",
    "energy": 0.63, "danceability": 0.86, "loudness": 78.0,
    "mood_happy": 0.807, "mood_sad": 0.47, "mood_aggressive": 0.039,
    "mood_relaxed": 0.267, "mood_party": 0.275, "mood_acoustic": 0.452,
    "voice_instrumental": 0.098
  },
  "audio_error": null,
  "lyrics": {"found": true, "source": "lrclib", "text": "..."}
}
```

- Áudio e letra são buscados em paralelo (duas threads) e são independentes.
- Se o áudio falha, `audio` é `null` e `audio_error` é um de: `age_restricted`, `forbidden`, `not_found`, `network`, `download_failed` (outro erro do yt-dlp), `analysis_failed` (baixou, mas a análise falhou). A letra ainda vem.
- Se a letra não é encontrada, `lyrics` é `{"found": false, "source": null, "text": null}`.
- `lyrics.text` é cortado em `LYRICS_MAX_CHARS` (padrão 3000).

### `GET /health`

`{"status": "ok", "tf_models_loaded": 8}`.

### Áudio (`audio.py`)

Mesmo comportamento do `audio-service/app.py` do Spotaste na `main` atual:

- Busca `"{track} {artist} official audio"` no YouTube (prefixo `ytsearch1:` explícito, para títulos como "re: stacks" não serem lidos como URL; duração < 600 s), extrai mp3, apaga o arquivo no fim.
- Essentia: BPM, tom/modo, loudness, energy, danceability.
- 8 heads MusiCNN, lendo a classe certa de cada um (`MOOD_HEADS`: happy 0, sad 1, aggressive 0, relaxed 1, party 1, voice_instrumental 0, acoustic 0, danceability 0). A danceability do modelo substitui a algorítmica.
- Erros do yt-dlp são classificados nas categorias de `audio_error` pela mensagem.

### Letras (`lyrics.py`)

Porta para Python do `packages/backend/src/lyrics.ts` do Spotaste:

- `clean_for_search(artist, title)`: remove ruído de título (Official Video, Remaster, feat., Ao Vivo, parênteses/colchetes) e sufixos de canal no artista.
- `fetch_lyrics(artist, title)`: tenta LRCLIB (`/api/search`, com User-Agent) e depois lyrics.ovh; para cada fonte, primeiro com nomes limpos e depois com o artista original se for diferente.
- LRCLIB: só aceita resultado cujo `artistName` normalizado (sem acento, sem pontuação, minúsculo) contém ou está contido no artista pedido, e com `plainLyrics` com mais de 20 caracteres.
- Timeout de 8 s por requisição. Respostas 429/502/503/504 (o LRCLIB responde 503 quando está ocupado) e erros de rede são tentados de novo, até três tentativas por busca; depois disso conta como "não encontrada".

### Execução

- gunicorn, `WEB_CONCURRENCY` workers (padrão 3), timeout 300 s. Modelos carregados na importação do módulo, uma cópia por worker.
- `docker-compose.yml` com `platform: linux/amd64` e a porta `127.0.0.1:5001`.
- `essentia-tensorflow==2.1b6.dev1389` fixo.

## Lote (`batch/`)

### `history.py`

- Aceita o zip ou a pasta do Extended Streaming History; lê os `Streaming_History_Audio_*.json`.
- Agrupa por `spotify_track_uri`; conta como play só quando `ms_played >= 30000`; soma o tempo total.
- Ordena por plays e depois por tempo, decrescente. Filtros: `min_plays`, `since` (ano), `limit`.

### `store.py`

SQLite em um arquivo (padrão `results.db`), uma tabela `tracks`:

`spotify_id` (PK), `track_name`, `artist_name`, `plays`, `status` (`done` ou `failed`), `audio` (JSON ou NULL), `audio_error`, `lyrics_found`, `lyrics_source`, `lyrics_text`, `analyzed_at`.

- `done` = o `/analyze` respondeu com áudio. `failed` = respondeu sem áudio (guarda o `audio_error` e a letra, se veio).
- Na retomada, pula as `done`; as `failed` são tentadas de novo só com `--retry-failed`.

### `import_history.py`

```
python -m batch.import_history <zip|pasta> [--min-plays N] [--limit N] [--since YYYY]
       [--concurrency N] [--retry-failed] [--dry-run] [--db results.db] [--url http://127.0.0.1:5001]
python -m batch.import_history export [--db results.db] [--out results.json]
```

- Concorrência padrão 1.
- Antes de começar, checa o `/health`; se o serviço não responde, sai com mensagem clara.
- Falha de conexão com o serviço ou `audio_error: network` não marca a música como `failed`: o script espera (30 s, dobrando até 5 min) e tenta a mesma música de novo. Isso evita queimar centenas de músicas quando a internet cai.
- Timeout de leitura (330 s) marca a música como `failed` com `audio_error: timeout`; resposta diferente de 200 marca `service_error`. Essas duas categorias só existem no lote.
- Progresso a cada 10 músicas, com ETA por tempo de relógio.
- `export` grava um JSON com uma lista de objetos no mesmo formato da resposta do `/analyze`, mais `spotify_id` e `plays`.

## Testes

Unitários (pytest, sem rede, rodam no host):

- `lyrics`: limpeza de nomes; aceitação/rejeição por artista com respostas simuladas do LRCLIB; queda para lyrics.ovh.
- `history`: contagem de plays com o corte de 30 s, ordenação, filtros, leitura de zip e de pasta.
- `store`: gravar, retomar pulando `done`, `--retry-failed`.
- `audio`: classificação das mensagens de erro do yt-dlp nas categorias; `MOOD_HEADS` confere com a tabela acima. (Essentia não é importado nesses testes: a classificação de erro e a tabela ficam em um módulo sem dependência pesada.)

Ponta a ponta (manual, documentado no README): `docker compose up`, `/health` com 8 modelos, analisar três músicas que já estão no banco do Spotaste e conferir que BPM, tom e moods ficam próximos (a busca no YouTube pode variar levemente o áudio).

## README

Em português, escrito para alguém (ou um modelo) adaptar o código: o que o serviço faz, como subir, contrato do `/analyze` com exemplo, fluxo do lote, significado e escala de cada feature, e limites conhecidos:

- ~15 s por música; em Apple Silicon roda emulado e não sustenta mais de 1 de concorrência por muito tempo.
- YouTube bloqueia parte dos downloads (403, restrição de idade); ~8% de falha no histórico testado.
- Cobertura de letras em torno de 80%.
- O áudio vem do primeiro resultado do YouTube, que pode ser outra versão da faixa.
- Letras são protegidas por direito autoral: o texto serve para análise; exibi-lo integralmente em um site é outra questão.

## Repositório

`github.com/leitejoaov/music-analyzer`, privado, conta pessoal (fora da org `brendi-tech`). Código e comentários em inglês.
