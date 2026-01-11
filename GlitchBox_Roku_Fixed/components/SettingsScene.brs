sub init()
    m.serverLabel = m.top.findNode("serverLabel")
    m.connectionLabel = m.top.findNode("connectionLabel")
    m.userLabel = m.top.findNode("userLabel")
    m.syncLabel = m.top.findNode("syncLabel")
    m.syncStatusLabel = m.top.findNode("syncStatusLabel")
    m.userHistory = m.top.findNode("userHistory")
    m.actions = m.top.findNode("actions")

    if m.actions <> invalid then
        m.actions.buttons = ["Set Server", "Test Connection", "Create User", "Sync Now", "Logout", "Reset App", "Disconnect", "Back"]
        m.actions.observeField("buttonSelected", "onActionSelected")
        m.actions.setFocus(true)
    end if

    if m.userHistory <> invalid then
        m.userHistory.observeField("itemSelected", "onUserHistorySelected")
        refreshUserHistory()
    end if

    host = loadServerHost()
    if host <> "" then
        m.top.serverHost = host
        updateServerLabel(host)
    else
        updateServerLabel("")
    end if
    updateConnectionLabel("Connection: not tested")

    user = loadUser()
    updateUserLabel(user)
    updateSyncLabel(loadLastSync())
    updateSyncStatusLabel("Sync Status: idle")

    m.top.observeField("syncStatus", "onSyncStatusChanged")
    m.top.observeField("lastSync", "onLastSyncChanged")
    ' Restore focus whenever Settings becomes visible
    m.top.observeField("visible", "onVisibleChanged")
    m.focusTarget = "actions"
end sub

sub onVisibleChanged(event as Object)
    if m.top.visible <> true then return

    ' Always ensure something focusable has focus when Settings is shown
    if m.focusTarget = invalid then m.focusTarget = "actions"

    if m.focusTarget = "history" and m.userHistory <> invalid and m.userHistory.content <> invalid and m.userHistory.content.getChildCount() > 0 then
        m.userHistory.setFocus(true)
    else if m.actions <> invalid then
        m.actions.setFocus(true)
        m.focusTarget = "actions"
    else if m.userHistory <> invalid then
        m.userHistory.setFocus(true)
        m.focusTarget = "history"
    end if
end sub

sub onActionSelected(event as Object)
    idx = event.getData()
    if idx = 0 then
        showServerInput()
    else if idx = 1 then
        testConnection()
    else if idx = 2 then
        showUserInput()
    else if idx = 3 then
        m.top.syncRequested = true
        m.top.syncStatus = "Sync Status: syncing..."
    else if idx = 4 then
        confirmLogout()
    else if idx = 5 then
        confirmReset()
    else if idx = 6 then
        showDisconnectConfirm()
    else if idx = 7 then
        m.top.backRequested = true
    end if
end sub

sub confirmLogout()
    dialog = CreateObject("roSGNode", "Dialog")
    dialog.title = "Logout"
    dialog.message = "Clear current user?"
    dialog.buttons = ["Cancel", "Logout"]
    dialog.observeField("buttonSelected", "onLogoutConfirm")
    m.top.getScene().dialog = dialog
end sub

sub onLogoutConfirm(event as Object)
    dialog = event.getRoSGNode()
    buttonIdx = dialog.buttonSelected
    if buttonIdx = 1 then
        clearUser()
        updateUserLabel({ username: "", userId: "" })
    end if
    m.top.getScene().dialog = invalid
end sub

sub confirmReset()
    dialog = CreateObject("roSGNode", "Dialog")
    dialog.title = "Reset App"
    dialog.message = "Clear server, user, and progress?"
    dialog.buttons = ["Cancel", "Reset"]
    dialog.observeField("buttonSelected", "onResetConfirm")
    m.top.getScene().dialog = dialog
end sub

sub onResetConfirm(event as Object)
    dialog = event.getRoSGNode()
    buttonIdx = dialog.buttonSelected
    if buttonIdx = 1 then
        clearServerHost()
        clearUser()
        clearProgressKeys()
        updateServerLabel("")
        updateUserLabel({ username: "", userId: "" })
    end if
    m.top.getScene().dialog = invalid
end sub

sub showUserInput()
    keyboard = CreateObject("roSGNode", "KeyboardDialog")
    keyboard.title = "GlitchBox User"
    keyboard.message = "Enter a username for progress tracking"
    existing = loadUser()
    if existing.username <> invalid then
        keyboard.text = existing.username
    else
        keyboard.text = ""
    end if
    keyboard.buttons = ["OK", "Cancel"]
    keyboard.observeField("buttonSelected", "onUserInputComplete")
    m.top.getScene().dialog = keyboard
end sub

sub onUserInputComplete(event as Object)
    dialog = event.getRoSGNode()
    buttonIdx = dialog.buttonSelected

    if buttonIdx = 0 then
        username = dialog.text
        if username = invalid then username = ""
        ' NOTE: Use roString method Trim() (Trim() global may not exist)
        username = username.Trim()
        if username <> "" then
            createUser(username)
        end if
    end if

    m.top.getScene().dialog = invalid
end sub

sub showDisconnectConfirm()
    dialog = CreateObject("roSGNode", "Dialog")
    dialog.title = "Disconnect"
    dialog.message = "Clear saved server and disconnect?"
    dialog.buttons = ["Cancel", "Disconnect"]
    dialog.observeField("buttonSelected", "onDisconnectConfirm")
    m.top.getScene().dialog = dialog
end sub

sub onDisconnectConfirm(event as Object)
    dialog = event.getRoSGNode()
    buttonIdx = dialog.buttonSelected

    if buttonIdx = 1 then
        clearServerHost()
        m.top.serverHost = ""
        updateServerLabel("")
    end if

    m.top.getScene().dialog = invalid
end sub

sub showServerInput()
    keyboard = CreateObject("roSGNode", "KeyboardDialog")
    keyboard.title = "GlitchBox Server"
    keyboard.message = "Enter server IP or FQDN"
    keyboard.text = m.top.serverHost
    keyboard.buttons = ["OK", "Cancel"]
    keyboard.observeField("buttonSelected", "onServerInputComplete")
    m.top.getScene().dialog = keyboard
end sub

sub onServerInputComplete(event as Object)
    dialog = event.getRoSGNode()
    buttonIdx = dialog.buttonSelected

    if buttonIdx = 0 then
        host = dialog.text
        if host = invalid then host = ""
        host = normalizeHostInput(host)

        if host <> "" then
            saveServerHost(host)
            m.top.serverHost = host
            updateServerLabel(host)
            updateConnectionLabel("Connection: not tested")
        end if
    end if

    m.top.getScene().dialog = invalid
end sub

function normalizeHostInput(raw as String) as String
    if raw = invalid then return ""
    ' NOTE: Use roString method Trim() (Trim() global may not exist)
    h = raw.Trim()

    if LCase(Left(h, 7)) = "http://" then h = Mid(h, 8)
    if LCase(Left(h, 8)) = "https://" then h = Mid(h, 9)

    slash = Instr(1, h, "/")
    if slash > 0 then h = Left(h, slash - 1)

    colon = Instr(1, h, ":")
    if colon > 0 then h = Left(h, colon - 1)

    return h
end function

function loadServerHost() as String
    section = CreateObject("roRegistrySection", "GlitchBox")
    if section.Exists("serverHost") then
        return section.Read("serverHost")
    end if
    return ""
end function

function buildBaseUrlFromHost(host as String) as String
    if host = "" then return ""
    return "http://" + host + ":8765"
end function

function loadUser() as Object
    section = CreateObject("roRegistrySection", "GlitchBox")
    user = {}
    if section.Exists("username") then user.username = section.Read("username")
    if section.Exists("userId") then user.userId = section.Read("userId")
    return user
end function

sub saveUser(username as String, userId as String)
    section = CreateObject("roRegistrySection", "GlitchBox")
    section.Write("username", username)
    section.Write("userId", userId)
    section.Flush()
    addUserToHistory(username, userId)
end sub

sub updateUserLabel(user as Object)
    if m.userLabel = invalid then return
    if user = invalid or user.username = invalid or user.username = "" then
        m.userLabel.text = "User: not set"
        return
    end if
    label = "User: " + user.username
    if user.userId <> invalid and user.userId <> "" then
        label = label + " (ID " + user.userId + ")"
    end if
    m.userLabel.text = label
end sub

sub refreshUserHistory()
    if m.userHistory = invalid then return
    content = CreateObject("roSGNode", "ContentNode")
    users = loadUserHistory()
    for each u in users
        node = content.createChild("ContentNode")
        node.title = u.username
        node.id = u.userId
    end for
    m.userHistory.content = content
end sub

sub onUserHistorySelected(event as Object)
    idx = event.getData()
    if m.userHistory = invalid or m.userHistory.content = invalid then return
    node = m.userHistory.content.getChild(idx)
    if node = invalid then return

    if node.title <> invalid and node.id <> invalid then
        saveUser(node.title, node.id)
        updateUserLabel({ username: node.title, userId: node.id })
    end if
end sub

function loadUserHistory() as Object
    section = CreateObject("roRegistrySection", "GlitchBox")
    if section.Exists("userHistory") then
        raw = section.Read("userHistory")
        parts = raw.Split("|")
        users = []
        for each p in parts
            kv = p.Split(":")
            if kv.Count() >= 2 then
                users.push({ username: kv[0], userId: kv[1] })
            end if
        end for
        return users
    end if
    return []
end function

sub addUserToHistory(username as String, userId as String)
    if username = "" or userId = "" then return
    users = loadUserHistory()
    updated = []

    for each u in users
        if u.userId <> userId then
            updated.push(u)
        end if
    end for

    updated.unshift({ username: username, userId: userId })
    if updated.Count() > 5 then
        updated = updated.Slice(0, 5)
    end if

    raw = ""
    for i = 0 to updated.Count() - 1
        u = updated[i]
        if i > 0 then raw = raw + "|"
        raw = raw + u.username + ":" + u.userId
    end for

    section = CreateObject("roRegistrySection", "GlitchBox")
    section.Write("userHistory", raw)
    section.Flush()
end sub

function loadLastSync() as String
    section = CreateObject("roRegistrySection", "GlitchBox")
    if section.Exists("lastSync") then
        return section.Read("lastSync")
    end if
    return ""
end function

sub updateSyncLabel(value as String)
    if m.syncLabel = invalid then return
    if value = "" then
        m.syncLabel.text = "Last Sync: never"
    else
        m.syncLabel.text = "Last Sync: " + value
    end if
end sub

sub updateSyncStatusLabel(value as String)
    if m.syncStatusLabel = invalid then return
    if value = "" then
        m.syncStatusLabel.text = "Sync Status: idle"
    else
        m.syncStatusLabel.text = value
    end if
end sub

sub onSyncStatusChanged(event as Object)
    status = event.getData()
    if status = invalid then status = ""
    updateSyncStatusLabel(status)
end sub

sub onLastSyncChanged(event as Object)
    value = event.getData()
    if value = invalid then value = ""
    updateSyncLabel(value)
end sub

sub saveServerHost(host as String)
    section = CreateObject("roRegistrySection", "GlitchBox")
    section.Write("serverHost", host)
    section.Flush()
end sub

sub clearServerHost()
    section = CreateObject("roRegistrySection", "GlitchBox")
    section.Delete("serverHost")
    section.Flush()
end sub

sub clearUser()
    section = CreateObject("roRegistrySection", "GlitchBox")
    section.Delete("username")
    section.Delete("userId")
    section.Delete("userHistory")
    section.Flush()
    refreshUserHistory()
end sub

sub clearProgressKeys()
    section = CreateObject("roRegistrySection", "GlitchBox")
    keys = section.GetKeyList()
    for each k in keys
        if Left(k, 9) = "progress_" then
            section.Delete(k)
        end if
    end for
    section.Flush()
end sub

sub updateServerLabel(host as String)
    if m.serverLabel = invalid then return
    if host = "" then
        m.serverLabel.text = "Server: not set"
    else
        m.serverLabel.text = "Server: " + host
    end if
end sub

sub updateConnectionLabel(value as String)
    if m.connectionLabel = invalid then return
    if value = "" then
        m.connectionLabel.text = "Connection: not tested"
    else
        m.connectionLabel.text = value
    end if
end sub

sub testConnection()
    host = loadServerHost()
    host = normalizeHostInput(host)
    if host = "" then
        updateConnectionLabel("Connection: set server first")
        return
    end if

    baseUrl = buildBaseUrlFromHost(host)
    updateConnectionLabel("Connection: testing...")

    m.testApiTask = CreateObject("roSGNode", "ApiTask")
    m.testApiTask.url = baseUrl + "/health"
    m.testApiTask.observeField("response", "onTestConnectionResponse")
    m.testApiTask.control = "RUN"
end sub

sub onTestConnectionResponse(event as Object)
    apiTask = event.getRoSGNode()

    if apiTask <> invalid and apiTask.responseCode = 200 then
        updateConnectionLabel("Connection: ok")
    else
        updateConnectionLabel("Connection: failed")
    end if

    ' Release retained task
    m.testApiTask = invalid
end sub

sub createUser(username as String)
    host = loadServerHost()
    host = normalizeHostInput(host)
    if host = "" then
        updateUserLabel({ username: "", userId: "" })
        return
    end if

    baseUrl = buildBaseUrlFromHost(host)
    url = baseUrl + "/users"
    body = { username: username }

    resp = postJson(url, body)
    if resp.code = 201 then
        json = ParseJson(resp.body)
        if json <> invalid and json.user_id <> invalid then
            uid = json.user_id.toStr()
            saveUser(username, uid)
            updateUserLabel({ username: username, userId: uid })
            refreshUserHistory()
            return
        end if
    end if

    updateUserLabel({ username: "Create failed", userId: "" })
end sub

function postJson(url as String, body as Object) as Object
    req = CreateObject("roUrlTransfer")
    req.SetUrl(url)
    req.AddHeader("Content-Type", "application/json")
    req.SetCertificatesFile("common:/certs/ca-bundle.crt")
    req.InitClientCertificates()
    port = CreateObject("roMessagePort")
    req.SetPort(port)

    payload = FormatJson(body)
    if req.AsyncPostFromString(payload) then
        while true
            msg = wait(5000, port)
            if type(msg) = "roUrlEvent" then
                return { code: msg.GetResponseCode(), body: msg.GetString() }
            else if msg = invalid then
                return { code: 0, body: "" }
            end if
        end while
    end if

    return { code: -1, body: "" }
end function

function onKeyEvent(key as String, press as Boolean) as Boolean
    if not press then return false

    if key = "back" then
        m.top.backRequested = true
        return true
    end if

    return false
end function
