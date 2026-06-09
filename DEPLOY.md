# SoroSoccer — Deploy no Railway

## Arquivos necessários

Você deve ter estes 5 arquivos numa pasta:

```
sorosoccer/
├── server.py
├── main.html
├── requirements.txt
├── Procfile
└── nixpacks.toml
```

---

## Passo 1 — Subir os arquivos no GitHub

1. Acesse https://github.com e faça login (ou crie uma conta grátis)
2. Clique em **"New repository"** (botão verde no canto superior direito)
3. Dê um nome ex: `sorosoccer`
4. Deixe como **Public** ou **Private** (tanto faz)
5. Clique em **"Create repository"**
6. Na página seguinte, clique em **"uploading an existing file"**
7. Arraste os 5 arquivos da pasta para a área de upload
8. Clique em **"Commit changes"**

---

## Passo 2 — Criar conta no Railway

1. Acesse https://railway.app
2. Clique em **"Login"** → **"Login with GitHub"**
3. Autorize o Railway a acessar sua conta GitHub

---

## Passo 3 — Criar o projeto

1. No painel do Railway, clique em **"New Project"**
2. Escolha **"Deploy from GitHub repo"**
3. Se aparecer "Configure GitHub App", clique e dê permissão ao repositório `sorosoccer`
4. Selecione o repositório na lista
5. Clique em **"Deploy Now"**

O Railway vai detectar automaticamente o `Procfile` e o `requirements.txt` e começar o build.

---

## Passo 4 — Aguardar o build

Na aba **"Deployments"** você vai ver os logs em tempo real. O processo normal é:

```
✔ Installing Python dependencies...
✔ Installing nixpacks (gcc, g++, binutils)...
✔ Build succeeded
✔ Deploying...
```

Se aparecer algum erro vermelho, copie a mensagem e me mande que eu ajudo.

---

## Passo 5 — Gerar a URL pública

1. Clique no seu projeto no painel do Railway
2. Vá em **"Settings"** (ícone de engrenagem)
3. Role até **"Networking"**
4. Clique em **"Generate Domain"**
5. Uma URL vai aparecer no formato:
   ```
   seu-app-nome.up.railway.app
   ```
   Copie essa URL.

---

## Passo 6 — Atualizar o main.html

Abra o arquivo `main.html` que você baixou e procure a linha:

```js
var WS_URL = 'wss://SEU-APP.up.railway.app';
```

Substitua `SEU-APP` pelo nome real que o Railway gerou. Exemplo:

```js
var WS_URL = 'wss://sorosoccer-production.up.railway.app';
```

Salve o arquivo.

---

## Passo 7 — Testar

1. Abra o `main.html` diretamente no navegador (pode abrir o arquivo local mesmo)
2. No canto inferior do simulador, você deve ver a mensagem:
   ```
   ✔ Conectado ao backend GCC. Pronto para compilar C++ real.
   ```
3. Escreva um código C++ e clique em **▶ EXECUTAR**

Se aparecer erro de conexão, veja a seção de problemas abaixo.

---

## Problemas comuns

**"WebSocket connection failed"**
- Confirme que a URL no `main.html` começa com `wss://` (não `ws://`)
- Confirme que o Railway gerou o domínio (Passo 5)
- Verifique nos logs do Railway se o servidor iniciou sem erros

**"g++: command not found" nos logs**
- Confirme que o arquivo `nixpacks.toml` está no repositório
- Vá em **Deployments → Redeploy** para forçar um novo build

**Build falhou com erro de Python**
- Verifique se o `requirements.txt` está no repositório com o conteúdo `websockets>=12.0`

---

## Plano gratuito do Railway

- **500 horas/mês** de execução — suficiente para uso normal
- O servidor **dorme após inatividade** e acorda automaticamente na próxima conexão (pode demorar ~5s na primeira vez)
- Se precisar que fique sempre ativo, o plano pago custa ~$5/mês
