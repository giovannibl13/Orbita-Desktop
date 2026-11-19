const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const assert = require('node:assert/strict');
const code = fs.readFileSync(path.join(__dirname, '../spotify_hook.js'), 'utf8');
const analysis = {track: {duration: 20, tempo: 120},
    beats: [{start: 1, duration: .5, confidence: .8}],
    segments: [{start: 0, duration: 20, loudness_start: -30, loudness_max_time: 1,
        loudness_max: -8, loudness_end: -35, pitches: Array(12).fill(.5)}]};
function harness({lyricsFail = false, analysisFail = false, holdAnalysis = false} = {}) {
    const posts = [], remote = [], audio = [];
    let tick, onChange, session = 'session-1', release;
    const player = {data: {item: {uri: 'spotify:track:' + 'A'.repeat(22)}},
        addEventListener(name, handler) { assert.equal(name, 'songchange'); onChange = handler; }};
    const context = {
        Spicetify: {Player: player, CosmosAsync: {async get(url) {
            assert.ok(url.startsWith('https://spclient.wg.spotify.com/color-lyrics/v2/track/'));
            remote.push(url);
            if (lyricsFail) throw Error('letra indisponível');
            return {lyrics: {syncType:'LINE_SYNCED', lines:[{startTimeMs:'1000',words:'Linha de teste'}]}};
        }}, async getAudioData(uri) {
            audio.push(uri);
            if (analysisFail) throw Error('análise indisponível');
            if (holdAnalysis) await new Promise(resolve => release = resolve);
            return analysis;
        }},
        async fetch(url, options) {
            assert.ok(url.startsWith('http://127.0.0.1:45739/'));
            assert.equal(options.headers['X-Orbita-Token'], '__ORBITA_LOCAL_TOKEN__');
            if (options.method === 'POST') posts.push({path: new URL(url).pathname, body: JSON.parse(options.body)});
            return {ok: true, async json() { return {session}; }};
        },
        AbortSignal, Date, setTimeout, clearTimeout,
        setInterval(handler) { tick = handler; },
    };
    vm.runInNewContext(code, context);
    return {posts, remote, audio, player, tick: () => tick(), change: () => onChange(),
        restart: () => session = 'session-2', release: () => release()};
}
const flush = () => new Promise(resolve => setImmediate(resolve));
(async () => {
    const h = harness();
    await flush(); await flush();
    assert.equal(h.posts.length, 2);
    assert.deepEqual(h.posts.map(p => p.path).sort(), ['/v1/analysis', '/v1/lyrics']);
    assert.equal(h.posts.find(p => p.path.endsWith('analysis')).body.beats[0][0], 1);
    await h.tick();
    assert.equal(h.posts.length, 2);
    assert.equal(h.audio.length, 1);
    h.player.data.item.uri = 'spotify:track:' + 'B'.repeat(22);
    await h.change();
    assert.equal(h.posts.length, 4);
    assert.ok(h.posts.slice(2).every(p => p.body.trackId === 'B'.repeat(22)));
    h.restart();
    await h.tick();
    assert.equal(h.posts.length, 6);
    assert.equal(h.audio.length, 2);
    const l = harness({lyricsFail: true});
    const a = harness({analysisFail: true});
    await flush(); await flush();
    assert.deepEqual(l.posts.map(p => p.path), ['/v1/analysis']);
    assert.deepEqual(a.posts.map(p => p.path), ['/v1/lyrics']);
    const stale = harness({holdAnalysis: true});
    await flush();
    stale.player.data.item.uri = 'spotify:track:' + 'B'.repeat(22);
    stale.release();
    await flush(); await flush();
    assert.equal(stale.posts.filter(p => p.path === '/v1/analysis').length, 0);
    console.log('Conector aprovado: ritmo e letras independentes, troca de faixa, pausa de consultas, reinício e descarte de resposta antiga');
})().catch(error => { console.error(error); process.exitCode = 1; });
