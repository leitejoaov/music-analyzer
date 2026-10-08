# music-analyzer

Análise musical por faixa: dado o nome da música e o artista, devolve **features de áudio** (BPM, tom, energia, moods) e a **letra**, em um único JSON. Inclui um script de lote que processa um export do Spotify inteiro.

Extraído do [Spotaste](https://github.com/leitejoaov/spotaste-monorep) para servir de referência a outros projetos. Não tem autenticação, fila multiusuário nem interpretação da letra (temas, idioma): isso fica com quem consome.

## Como funciona

Para cada música, o serviço faz duas coisas em paralelo:

1. **Áudio:** busca `"{música} {artista} official audio"` no YouTube (yt-dlp), baixa o primeiro resultado com menos de 10 minutos e analisa o arquivo com [Essentia](https://essentia.upf.edu/) e 8 modelos MusiCNN.
2. **Letra:** busca no [LRCLIB](https://lrclib.net) e, se não achar, no [lyrics.ovh](https://lyrics.ovh).

As duas partes são independentes: se o YouTube bloquear o download, a resposta ainda traz a letra.

## Subir o serviço

```bash
docker compose up -d --build
curl http://127.0.0.1:5001/health
```

O `/health` deve responder `{"status": "ok", "tf_models_loaded": 8}`. A primeira build baixa os modelos e demora alguns minutos.

Variáveis de ambiente (todas opcionais):

| Variável | Padrão | O que faz |
|---|---|---|
| `ANALYZER_PORT` | `5001` | Porta no host |
| `WEB_CONCURRENCY` | `3` | Workers do gunicorn; cada um usa ~1,3 GB de RAM |
| `LYRICS_MAX_CHARS` | `3000` | Tamanho máximo do texto da letra |

## API

### `POST /analyze`

```bash
curl -X POST http://127.0.0.1:5001/analyze \
  -H 'Content-Type: application/json' \
  -d '{"track": "Sweater Weather", "artist": "The Neighbourhood"}'
```

```json
{
  "track": "Sweater Weather",
  "artist": "The Neighbourhood",
  "audio": {
    "bpm": 123.9, "key": "Bb", "mode": "major",
    "energy": 0.63, "danceability": 0.87, "loudness": 78.0,
    "mood_happy": 0.812, "mood_sad": 0.472, "mood_aggressive": 0.029,
    "mood_relaxed": 0.274, "mood_party": 0.263, "mood_acoustic": 0.496,
    "voice_instrumental": 0.086
  },
  "audio_error": null,
  "lyrics": {"found": true, "source": "lrclib", "text": "..."}
}
```

- Responde **200 sempre que a entrada é válida**, mesmo quando o áudio ou a letra falham. Sem `track` ou `artist`, responde 400.
- Quando o áudio falha, `audio` é `null` e `audio_error` traz o motivo.
- Quando a letra não é encontrada, `lyrics` é `{"found": false, "source": null, "text": null}`.
- Uma chamada leva em torno de 15 segundos.

### Features de áudio

| Campo | Escala | Significado |
|---|---|---|
| `bpm` | número | Andamento. Erros de dobro/metade são comuns em detecção de tempo |
| `key`, `mode` | `C`…`B`, `major`/`minor` | Tom estimado. É a feature menos confiável |
| `energy` | 0–1 | Energia do sinal, normalizada pela duração. Não é a "energy" do Spotify |
| `loudness` | número positivo | `20·log10` da loudness do Essentia; escala relativa, não é LUFS |
| `danceability` | 0–1 | Probabilidade de ser dançante (modelo) |
| `mood_happy`, `mood_sad`, `mood_aggressive`, `mood_relaxed`, `mood_party`, `mood_acoustic` | 0–1 | Probabilidade de cada mood. São classificadores independentes: uma música pode ser alta em `happy` e `sad` ao mesmo tempo |
| `voice_instrumental` | 0–1 | 1 = instrumental, 0 = vocal |

Se os modelos de mood falharem para uma faixa, os campos `mood_*` e `voice_instrumental` ficam ausentes e os demais ainda vêm.

### Valores de `audio_error`

| Valor | Causa |
|---|---|
| `age_restricted` | O vídeo exige login para confirmar a idade |
| `forbidden` | O YouTube recusou o download (HTTP 403). Às vezes passa em outra tentativa |
| `not_found` | Nenhum resultado utilizável na busca |
| `network` | O container está sem internet |
| `download_failed` | Outro erro do yt-dlp |
| `analysis_failed` | O arquivo foi baixado, mas a análise falhou |

### `GET /health`

`{"status": "ok", "tf_models_loaded": 8}`. Pode demorar a responder enquanto todos os workers estão ocupados analisando.

## Lote: processar um export do Spotify

O script lê o **Extended Streaming History** (o zip que o Spotify envia quando você pede seus dados), ordena as músicas das mais ouvidas para as menos ouvidas, manda cada uma para o `/analyze` e grava o resultado em um arquivo SQLite.

Roda fora do container, com Python 3.11+:

```bash
pip install -r requirements-dev.txt
python -m batch.import_history ~/Downloads/my_spotify_data.zip --min-plays 4
```

| Opção | Padrão | O que faz |
|---|---|---|
| `--min-plays N` | `1` | Só músicas com pelo menos N plays de 30 s ou mais |
| `--limit N` | — | Só as N mais ouvidas |
| `--since YYYY` | — | Só plays desse ano em diante |
| `--concurrency N` | `1` | Requisições em paralelo |
| `--retry-failed` | — | Tenta de novo as que falharam em execuções anteriores |
| `--dry-run` | — | Mostra as contagens e sai |
| `--db ARQUIVO` | `results.db` | Onde gravar |
| `--url URL` | `http://127.0.0.1:5001` | Endereço do serviço |

Comportamento:

- **Pode interromper e rodar de novo:** ele pula o que já foi processado.
- **Play = 30 segundos ou mais.** Skips não contam.
- **Queda de internet não queima a lista:** se o serviço não responde ou devolve `network`, o script espera (30 s, dobrando até 5 min) e tenta a mesma música de novo.
- **Falhas ficam registradas** com o motivo, e com a letra se ela foi encontrada.

Para exportar tudo em JSON:

```bash
python -m batch.import_history export --out results.json
```

Cada item tem o mesmo formato da resposta do `/analyze`, mais `spotify_id` e `plays`.

### Tabela `tracks` (SQLite)

`spotify_id` (PK), `track_name`, `artist_name`, `plays`, `status` (`done` = tem áudio, `failed` = sem áudio), `audio` (JSON), `audio_error`, `lyrics_found`, `lyrics_source`, `lyrics_text`, `analyzed_at`.

## Limites conhecidos

Medidos processando um histórico real de ~7.400 músicas:

- **Velocidade:** ~15 s por música. Em Apple Silicon o container roda emulado (o Essentia só tem pacote Linux x86_64) e, em uso prolongado, a máquina esquenta; por isso a concorrência padrão do lote é 1. Em uma máquina x86 com vários núcleos, 3 workers com `--concurrency 3` aguentam bem.
- **Bloqueios do YouTube:** cerca de 8% das músicas falham por 403 ou restrição de idade.
- **Versão errada:** a análise usa o primeiro resultado do YouTube, que às vezes é outra versão (ao vivo, acústica, remix).
- **Cobertura de letras:** em torno de 80%. Faltam principalmente instrumentais e faixas pouco conhecidas.
- **LRCLIB ocupado:** o LRCLIB às vezes responde 503; o serviço tenta três vezes antes de desistir.
- **Letras têm direito autoral:** o texto serve para análise. Exibir a letra inteira em um site é outra questão e exige licença.

## Estrutura

```
analyzer/            roda dentro do container
  app.py             API Flask
  audio.py           download + Essentia + modelos de mood
  lyrics.py          LRCLIB e lyrics.ovh
  meta.py            índice das classes dos modelos e categorias de erro
  download_models.py baixa os modelos na build
batch/               roda no host
  history.py         leitura e ranking do export do Spotify
  store.py           resultados em SQLite
  import_history.py  CLI
tests/               pytest, sem rede
```

## Testes

```bash
pip install -r requirements-dev.txt
python -m pytest
```

Os testes não usam rede nem Essentia. Para conferir o serviço de ponta a ponta, suba o container e analise algumas músicas conhecidas com o `curl` acima.
