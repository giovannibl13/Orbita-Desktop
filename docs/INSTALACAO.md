# Instalação e compatibilidade

## Ambiente suportado

A versão 1.0.0 foi preparada e validada no Zorin OS 18.1 com GNOME Shell 46, Wayland e PipeWire. O instalador aceita GNOME 46. Ubuntu 24.04 com GNOME 46 possui a base de dependências usada pelo pacote, mas outras distribuições não foram verificadas visualmente.

O pacote usa arquitetura `all`: a extensão e os auxiliares são interpretados. A conexão opcional com Spotify inclui uma verificação separada para x86_64, pois baixa o Spicetify Linux amd64.

A instalação do .deb não executa a extensão como administrador nem altera automaticamente a configuração de contas. Ela instala o configurador e suas dependências. Cada usuário abre o configurador e ativa o visual em sua própria sessão.

## Arquivos instalados

| Local | Uso |
| --- | --- |
| `/usr/share/orbita-desktop` | Arquivos do pacote .deb, somente leitura para o usuário |
| `/usr/bin/orbita-desktop` | Abre o configurador ou executa uma ação |
| `~/.local/share/gnome-shell/extensions/orbita-desktop@local` | Extensão ativada na conta |
| `~/.local/share/orbita-spotify` | Cópia local do Spotify e Spicetify |
| `~/.config/orbita-desktop/spotify.json` | Chave e porta do receptor local |
| `~/.config/systemd/user/orbita-letras.service` | Serviço local de letras e análise |
| `~/.cache/orbita-desktop` | Letras, análise e capas em cache |
| `~/.local/state/orbita-desktop` | Registro da instalação na conta |

Os diretórios seguem `XDG_DATA_HOME`, `XDG_CONFIG_HOME`, `XDG_CACHE_HOME` e `XDG_STATE_HOME` quando definidos. A gravação de estado fica fora do diretório somente leitura do pacote.

## Linha de comando

```bash
orbita-desktop --verificar
orbita-desktop --instalar
orbita-desktop --spotify
orbita-desktop --desativar
orbita-desktop --remover
orbita-desktop --versao
```

A ativação e a remoção não devem ser executadas com `sudo`.

## Se o visual não aparecer

Confirme `gnome-shell --version`, saia e entre na sessão e abra a segunda área de trabalho. Confira a extensão em `gnome-extensions info orbita-desktop@local`. O pacote não troca o fundo das outras áreas e não aparece em monitores secundários.

## Se a integração do Spotify não conectar

Use o Spotify instalado em `/usr/share/spotify`, abra-o e faça login uma vez. Feche-o antes de preparar a conexão. Depois abra o Spotify pelo menu de aplicativos, que usa o atalho configurado pelo Órbita.

A integração depende de APIs e da estrutura do cliente Spotify. Se uma faixa não tiver letra ou análise, as fontes alternativas e o modo ambiente continuam disponíveis. Atualizações do Spotify ou do Spicetify podem exigir ajustes futuros deste projeto.

## Remoção completa

Feche o Spotify, remova a ativação pelo configurador e então remova o .deb com `sudo apt remove orbita-desktop`. Remover apenas o .deb não acessa os arquivos privados de todas as contas; por isso a etapa de remoção por usuário vem primeiro.
