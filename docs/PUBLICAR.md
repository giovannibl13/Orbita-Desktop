# Publicar no GitHub

O repositório oficial é [giovannibl13/Orbita-Desktop](https://github.com/giovannibl13/Orbita-Desktop). Estas instruções também servem para publicar uma cópia em outro repositório.

## Enviar o código-fonte

Crie um repositório vazio no seu GitHub. Na pasta com `README.md`, `extension.js` e `VERSION`, execute:

```bash
git init -b main
git add .
git commit -m "Publica Órbita 1.0.0"
git remote add origin https://github.com/giovannibl13/Orbita-Desktop.git
git push -u origin main
```

O `.gitignore` exclui arquivos gerados, caches, logs e configurações locais. O programa e as imagens têm licenças diferentes, registradas em `LICENSE`, `THIRD_PARTY_NOTICES.md` e `licenses/`.

## Publicar os instaladores automaticamente

O workflow roda no Ubuntu 24.04, testa o código e gera os arquivos da versão. Uma tag com a versão de `VERSION` publica a Release e anexa os instaladores e os checksums:

A primeira publicação, **1.0.0**, também é gerada automaticamente ao enviar o projeto para `main`, após os testes passarem. As próximas versões são publicadas por tags.

```bash
git tag v1.0.0
git push origin v1.0.0
```

O workflow usa o `GITHUB_TOKEN` fornecido pelo GitHub Actions, com permissão para criar a Release. Não é necessário colocar tokens pessoais nos arquivos do projeto. Se a política da conta bloquear permissões de escrita para Actions, habilite a permissão adequada ao repositório.

Nas próximas versões, atualize `VERSION`, `CHANGELOG.md` e as notas da versão antes de enviar uma nova tag. Se o desenho da extensão mudar, incremente também o número inteiro em `metadata.json`.

## Publicar os arquivos já gerados

Também é possível criar uma Release pela interface do GitHub e anexar os arquivos de `dist/`:

- `orbita-desktop_1.0.0_all.deb` — instalação pelo gerenciador de pacotes.
- `orbita-desktop-1.0.0-portatil.tar.gz` — instalação por usuário, sem o .deb.
- `orbita-desktop-1.0.0-codigo-fonte.zip` — fonte, testes, documentação e geração dos pacotes.
- `SHA256SUMS` — conferência de integridade.

Pelo site, abra **Releases → Draft a new release**, crie a tag `v1.0.0`, use o título **Órbita 1.0.0**, anexe os quatro arquivos e clique em **Publish release**. O workflow reconhece uma Release já criada pelo site e preserva os arquivos anexados manualmente.

Na pasta dos downloads, o usuário pode conferir:

```bash
sha256sum -c SHA256SUMS
```

Não adicione o Spotify, a cópia local modificada, arquivos de preferências, tokens nem caches pessoais ao repositório ou à Release. Eles não são necessários para instalar o Órbita.
