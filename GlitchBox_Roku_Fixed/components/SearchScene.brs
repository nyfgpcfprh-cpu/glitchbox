sub init()
    m.actions = m.top.findNode("actions")
    m.results = m.top.findNode("results")
    m.status = m.top.findNode("status")
    m.scopeLabel = m.top.findNode("scopeLabel")
    m.pageLabel = m.top.findNode("pageLabel")
    m.errorDialog = m.top.findNode("errorDialog")
    m.query = ""
    m.baseUrl = ""
    m.items = []
    m.searchQueue = []
    m.searchResults = []
    m.scope = "current"
    m.limit = 50
    m.offset = 0
    m.page = 0
    m.libraryOffsets = {}
    m.libraryCounts = {}
    m.currentLibId = ""

    if m.actions <> invalid then
        m.actions.buttons = ["Enter Query", "Prev Page", "Next Page", "Retry", "Toggle Scope", "Clear", "Back"]
        m.actions.observeField("buttonSelected", "onActionSelected")
        m.actions.setFocus(true)
    end if

    if m.results <> invalid then
        m.results.observeField("rowItemSelected", "onResultSelected")
    end if

    updateScopeLabel()
    updatePageLabel()
end sub

sub onActionSelected(event as Object)
    idx = event.getData()
    if idx = 0 then
        showQueryInput()
    else if idx = 1 then
        prevPage()
    else if idx = 2 then
        nextPage()
    else if idx = 3 then
        retrySearch()
    else if idx = 4 then
        toggleScope()
    else if idx = 5 then
        clearResults()
    else if idx = 6 then
        m.top.backRequested = true
    end if
end sub

sub showQueryInput()
    keyboard = CreateObject("roSGNode", "KeyboardDialog")
    keyboard.title = "Search"
    keyboard.message = "Search title or path"
    keyboard.text = m.query
    keyboard.buttons = ["OK", "Cancel"]
    keyboard.observeField("buttonSelected", "onQueryComplete")
    m.top.getScene().dialog = keyboard
end sub

sub onQueryComplete(event as Object)
    dialog = event.getRoSGNode()
    buttonIdx = dialog.buttonSelected

    if buttonIdx = 0 then
        q = dialog.text
        if q = invalid then q = ""
        q = q.Trim()
        if q <> "" then
            m.query = q
            runSearch(q)
        end if
    end if

    m.top.getScene().dialog = invalid
end sub

sub runSearch(q as String)
    host = normalizeHostInput(m.top.serverHost)
    if host = "" then
        showError("Set server in Settings first")
        return
    end if

    m.baseUrl = buildBaseUrlFromHost(host)

    m.offset = 0
    m.page = 0
    m.libraryOffsets = {}
    m.searchQueue = buildSearchTargets()
    m.searchResults = []
    m.libraryCounts = {}

    if m.searchQueue.Count() = 0 then
        showError("No libraries available")
        return
    end if

    setStatus("Searching...")
    searchNext(q)
end sub

sub onSearchResponse(event as Object)
    apiTask = event.getRoSGNode()

    if apiTask.responseCode <> 200 then
        showError("Search failed (" + apiTask.responseCode.toStr() + ")")
        return
    end if

    json = ParseJson(apiTask.response)
    if json = invalid or json.items = invalid then
        showError("Invalid search response")
        return
    end if

    if m.currentLibId <> "" then
        m.libraryCounts[m.currentLibId] = json.items.Count()
    end if

    for each item in json.items
        m.searchResults.push(item)
    end for

    updatePageLabel()

    if m.searchQueue.Count() > 0 then
        searchNext(m.query)
        return
    end if

    m.items = m.searchResults
    renderResults()
end sub

sub searchNext(q as String)
    if m.searchQueue.Count() = 0 then return
    libId = m.searchQueue[0]
    m.searchQueue.Delete(0, 1)
    m.currentLibId = libId

    encoded = urlEncode(q)
    if m.scope = "all" then
        if m.libraryOffsets[libId] = invalid then
            m.libraryOffsets[libId] = 0
        end if
        m.offset = m.libraryOffsets[libId]
    end if
    url = m.baseUrl + "/libraries/" + libId + "/media-files?limit=" + m.limit.toStr() + "&offset=" + m.offset.toStr() + "&q=" + encoded

    apiTask = CreateObject("roSGNode", "ApiTask")
    apiTask.url = url
    apiTask.observeField("response", "onSearchResponse")
    apiTask.control = "RUN"
end sub

sub renderResults()
    contentRoot = CreateObject("roSGNode", "ContentNode")

    row = contentRoot.createChild("ContentNode")
    row.title = "Results"

    for each item in m.items
        node = row.createChild("ContentNode")
        title = "Untitled"
        if item.title <> invalid and item.title <> "" then title = item.title
        node.title = title

        posterUrl = ""
        if item.poster_url <> invalid and item.poster_url <> "" then
            posterUrl = item.poster_url
        else if item.posterUrl <> invalid and item.posterUrl <> "" then
            posterUrl = item.posterUrl
        else if item.poster_path <> invalid and item.poster_path <> "" then
            posterUrl = item.poster_path
        end if

        if posterUrl <> "" and Left(posterUrl, 1) = "/" then
            posterUrl = m.baseUrl + posterUrl
        end if
        if posterUrl = "" then posterUrl = "pkg:/images/icon_side_hd.png"

        node.HDPosterUrl = posterUrl
        node.SDPosterUrl = posterUrl
    end for

    if m.results <> invalid then
        m.results.content = contentRoot
    end if

    if m.items.Count() = 0 then
        setStatus("No results")
    else
        setStatus("Results: " + m.items.Count().toStr())
    end if
end sub

sub onResultSelected(event as Object)
    sel = event.getData()
    if sel = invalid or sel.Count() < 2 then return
    idx = sel[1]
    if idx < 0 or idx >= m.items.Count() then return

    item = m.items[idx]
    posterUrl = ""
    if item.poster_url <> invalid and item.poster_url <> "" then
        posterUrl = item.poster_url
    else if item.posterUrl <> invalid and item.posterUrl <> "" then
        posterUrl = item.posterUrl
    else if item.poster_path <> invalid and item.poster_path <> "" then
        posterUrl = item.poster_path
    end if

    if posterUrl <> "" and Left(posterUrl, 1) = "/" then
        posterUrl = m.baseUrl + posterUrl
    end if

    m.top.selectedItem = {
        id: item.id,
        title: item.title,
        poster: posterUrl,
        url: buildPlaybackUrl(item.id),
        streamFormat: "hls"
    }
end sub

sub clearResults()
    m.query = ""
    m.offset = 0
    m.page = 0
    m.libraryOffsets = {}
    m.libraryCounts = {}
    updatePageLabel()
    m.items = []
    m.searchResults = []
    if m.results <> invalid then
        m.results.content = CreateObject("roSGNode", "ContentNode")
    end if
    if m.errorDialog <> invalid then m.errorDialog.visible = false
    setStatus("Cleared")
end sub

sub nextPage()
    if m.query = "" then
        showError("No query")
        return
    end if
    m.page = m.page + 1
    m.offset = m.page * m.limit
    if m.scope = "all" then
        updateLibraryOffsets(true)
    end if
    updatePageLabel()
    runSearch(m.query)
end sub

sub prevPage()
    if m.query = "" then
        showError("No query")
        return
    end if
    m.page = m.page - 1
    if m.page < 0 then m.page = 0
    m.offset = m.page * m.limit
    if m.scope = "all" then
        updateLibraryOffsets(false)
    end if
    updatePageLabel()
    runSearch(m.query)
end sub

sub updateLibraryOffsets(isNextPage as Boolean)
    if m.top.libraries = invalid then return
    for each lib in m.top.libraries
        if lib <> invalid and lib.id <> invalid then
            libId = lib.id.toStr()
            if m.libraryOffsets[libId] = invalid then m.libraryOffsets[libId] = 0
            if isNextPage then
                count = m.libraryCounts[libId]
                if count = invalid or count >= m.limit then
                    m.libraryOffsets[libId] = m.libraryOffsets[libId] + m.limit
                end if
            else
                m.libraryOffsets[libId] = m.libraryOffsets[libId] - m.limit
                if m.libraryOffsets[libId] < 0 then m.libraryOffsets[libId] = 0
            end if
        end if
    end for
end sub

sub retrySearch()
    if m.query = "" then
        showError("No previous query")
        return
    end if
    runSearch(m.query)
end sub

sub toggleScope()
    if m.scope = "current" then
        m.scope = "all"
    else
        m.scope = "current"
    end if
    updateScopeLabel()
    updatePageLabel()
end sub

sub updateScopeLabel()
    if m.scopeLabel = invalid then return
    if m.scope = "all" then
        m.scopeLabel.text = "Scope: All Libraries"
    else
        m.scopeLabel.text = "Scope: Current Library"
    end if
end sub

sub updatePageLabel()
    if m.pageLabel = invalid then return

    label = "Page: " + (m.page + 1).toStr()
    if m.scope = "current" then
        name = ""
        if m.top.libraries <> invalid then
            for each lib in m.top.libraries
                if lib <> invalid and lib.id <> invalid and lib.id.toStr() = m.top.libraryId then
                    if lib.name <> invalid and lib.name <> "" then name = lib.name
                    exit for
                end if
            end for
        end if
        if name <> "" then label = label + " (" + name + ")"
    else
        label = label + " (All Libraries)"
    end if
    m.pageLabel.text = label
end sub

function buildSearchTargets() as Object
    targets = []
    if m.scope = "current" then
        if m.top.libraryId <> invalid and m.top.libraryId <> "" then
            targets.push(m.top.libraryId)
        end if
        return targets
    end if

    if m.top.libraries <> invalid then
        for each lib in m.top.libraries
            if lib <> invalid and lib.id <> invalid then
                targets.push(lib.id.toStr())
            end if
        end for
    end if
    return targets
end function

sub setStatus(msg as String)
    if m.status <> invalid then m.status.text = msg
end sub

sub showError(msg as String)
    setStatus(msg)
    if m.errorDialog <> invalid then
        m.errorDialog.message = msg
        m.errorDialog.visible = true
    end if
end sub

function normalizeHostInput(raw as String) as String
    if raw = invalid then return ""
    h = raw.Trim()

    if LCase(Left(h, 7)) = "http://" then h = Mid(h, 8)
    if LCase(Left(h, 8)) = "https://" then h = Mid(h, 9)

    slash = Instr(1, h, "/")
    if slash > 0 then h = Left(h, slash - 1)

    colon = Instr(1, h, ":")
    if colon > 0 then h = Left(h, colon - 1)

    return h
end function

function buildBaseUrlFromHost(host as String) as String
    if host = "" then return ""
    return "http://" + host + ":8765"
end function

function buildPlaybackUrl(id as Dynamic) as String
    if m.baseUrl = "" then return ""
    if id = invalid then return ""
    return m.baseUrl + "/hls/" + id.toStr() + "/master.m3u8"
end function

function urlEncode(s as String) as String
    t = CreateObject("roUrlTransfer")
    return t.Escape(s)
end function

function onKeyEvent(key as String, press as Boolean) as Boolean
    if not press then return false

    if key = "back" then
        m.top.backRequested = true
        return true
    end if

    if key = "*" then
        m.top.backRequested = true
        return true
    end if

    return false
end function
