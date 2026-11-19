// Executado dentro do Spotify pelo Spicetify. A sessão permanece no cliente.
(function orbitaMusic() {
    const endpoint = 'http://127.0.0.1:45739';
    const token = '__ORBITA_LOCAL_TOKEN__';
    let busy = false;
    let cachedTrack = '';
    let resources = [];

    const rounded = value => Math.round(Number(value) * 10000) / 10000;
    const bounded = (value, low, high) => Math.max(low, Math.min(high, Number(value) || 0));
    async function withinTime(request) {
        let timer;
        try {
            return await Promise.race([request, new Promise((_, reject) => {
                timer = setTimeout(() => reject(new Error('Tempo de consulta excedido')), 15000);
            })]);
        } finally {
            clearTimeout(timer);
        }
    }
    async function lyrics(trackId) {
        // Cosmos inclui a autenticação somente nesta URL do Spotify.
        const body = await Spicetify.CosmosAsync.get(
            'https://spclient.wg.spotify.com/color-lyrics/v2/track/' +
            trackId + '?format=json&vocalRemoval=false&market=from_token');
        if (!body?.lyrics?.lines?.length)
            return null;
        return {trackId, syncType: body.lyrics.syncType,
            lines: body.lyrics.lines.map(line => ({
                startTimeMs: Number(line.startTimeMs) || 0,
                words: String(line.words || ''),
            }))};
    }

    async function analysis(trackId) {
        if (!Spicetify.getAudioData)
            return null;
        const body = await Spicetify.getAudioData('spotify:track:' + trackId);
        if (!body?.beats?.length || !body?.segments?.length || !body?.track?.duration)
            return null;
        return {trackId, duration: rounded(body.track.duration),
            tempo: rounded(body.track.tempo || 0),
            beats: body.beats.map(beat => [rounded(beat.start), rounded(beat.duration),
                bounded(beat.confidence, 0, 1)]),
            segments: body.segments.map(segment => [rounded(segment.start), rounded(segment.duration),
                rounded(segment.loudness_start), rounded(bounded(segment.loudness_max_time, 0, segment.duration)),
                rounded(segment.loudness_max), rounded(segment.loudness_end || 0),
                segment.pitches.map(pitch => rounded(bounded(pitch, 0, 1)))]),
        };
    }

    async function sync(resource, trackId, uri, session) {
        try {
            if (!resource.result && Date.now() >= resource.retryAt) {
                resource.retryAt = Date.now() + 90000;
                resource.result = await withinTime(resource.load(trackId));
            }
            if (Spicetify.Player.data.item?.uri !== uri)
                return;
            if (resource.result && resource.delivered !== session + ':' + trackId) {
                await local('/v1/' + resource.path, {method: 'POST', body: JSON.stringify(resource.result)});
                resource.delivered = session + ':' + trackId;
            }
        } catch (_) {
            // As fontes são independentes: falha na letra preserva o ritmo e vice-versa.
            if (!resource.result)
                resource.retryAt = Date.now() + 30000;
        }
    }

    async function local(path, options = {}) {
        const response = await fetch(endpoint + path, {
            ...options,
            headers: {'Content-Type': 'application/json', 'X-Orbita-Token': token},
            signal: AbortSignal.timeout(2000),
        });
        if (!response.ok)
            throw new Error('Local receiver: ' + response.status);
        return response.json();
    }

    async function tick() {
        if (busy || !globalThis.Spicetify?.Player?.data || !Spicetify.CosmosAsync)
            return;
        const uri = Spicetify.Player.data.item?.uri || '';
        const match = /^spotify:track:([A-Za-z0-9]{22})$/.exec(uri);
        if (!match)
            return;
        const trackId = match[1];
        busy = true;
        try {
            const status = await local('/v1/status');
            if (trackId !== cachedTrack) {
                cachedTrack = trackId;
                resources = [
                    {path: 'lyrics', load: lyrics, result: null, retryAt: 0, delivered: ''},
                    {path: 'analysis', load: analysis, result: null, retryAt: 0, delivered: ''},
                ];
            }
            await Promise.allSettled(resources.map(resource => sync(resource, trackId, uri, status.session)));
        } catch (_) {
            // O receptor pode ainda estar iniciando. A próxima rodada tenta de novo.
        } finally {
            busy = false;
        }
    }

    const start = () => {
        if (!globalThis.Spicetify?.Player?.addEventListener || !Spicetify.CosmosAsync) {
            setTimeout(start, 500);
            return;
        }
        Spicetify.Player.addEventListener('songchange', tick);
        setInterval(tick, 2000);
        tick();
    };
    start();
})();
