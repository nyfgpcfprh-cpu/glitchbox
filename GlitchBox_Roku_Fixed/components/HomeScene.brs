sub init()
    if m.top.hasField("focusable") then m.top.focusable = true
    m.navList = m.top.findNode("navList")
    m.rows = m.top.findNode("rows")
    m.status = m.top.findNode("status")
    m.connectionBadge = invalid
    m.loadingOverlay = m.top.findNode("loadingOverlay")

    ' Global node (used for app-wide signals like Exit App)
    ' Scene nodes expose the global node via the built-in `global` field.
    ' Avoid using the variable name `global` (reserved / confusing in BrightScript).
    m.globalNode = invalid
    scene = m.top.getScene()
    if scene <> invalid and scene.hasField("global") then
        m.globalNode = scene.global
    end if

    m.baseUrl = ""
    m.rowTypes = []
    m.mediaItems = []
    m.libraries = []
    m.selectedLibraryId = ""
    m.selectedShowKey = ""
    m.selectedSeasonKey = ""
    m.tvShowKeys = []
    m.tvShowPosters = {}
    m.tvSeasonGroups = []
    m.pendingAction = ""
    m.pendingAutoConnect = false
    m.currentNavId = "home"
    m.isRefreshingNav = false

    if m.navList <> invalid then
        m.navList.observeField("itemSelected", "onNavSelected")
        m.navList.content = buildNavItemsForContext(m.currentNavId)

        ' Set the default selection first, then focus the rail.
        setNavSelectionById("home")

        ' Ensure HomeScene is the focus root before focusing children.
        m.top.setFocus(true)
        m.navList.setFocus(true)

        m.focusTarget = "nav"
    end if

    if m.rows <> invalid then
        m.rows.observeField("rowItemSelected", "onRowItemSelected")
    end if


    if m.top.hasField("serverHost") then m.top.observeField("serverHost", "onServerHostChanged")
    if m.top.hasField("visible") then m.top.observeField("visible", "onVisibleChanged")

    ' Support both legacy and newer sync trigger field names
    if m.top.hasField("syncRequested") then m.top.observeField("syncRequested", "onSyncRequested")
    if m.top.hasField("syncRequestedRequested") then m.top.observeField("syncRequestedRequested", "onSyncRequested")

    host = loadServerHost()
    if host <> "" then
        m.top.serverHost = host
        m.baseUrl = buildBaseUrlFromHost(host)
        startAutoConnect()
    else
        setConnectionState(false, "Disconnected: set server in Settings")
    end if

    if m.top.hasField("selectedLibraryId") then m.top.selectedLibraryId = m.selectedLibraryId
    if m.top.hasField("libraries") then m.top.libraries = m.libraries
end sub

sub onSyncRequested(event as Object)
    requested = false

    ' Support both possible trigger fields
    if m.top.hasField("syncRequested") then
        requested = (m.top.syncRequested = true)
    else if m.top.hasField("syncRequestedRequested") then
        requested = (m.top.syncRequestedRequested = true)
    end if

    if requested then
        ' Reset whichever field exists so the trigger is one-shot
        if m.top.hasField("syncRequested") then m.top.syncRequested = false
        if m.top.hasField("syncRequestedRequested") then m.top.syncRequestedRequested = false

        if m.baseUrl <> "" then
            fetchLibraries()
        else
            setConnectionState(false, "Set server in Settings")
        end if
    end if
end sub

sub onVisibleChanged(event as Object)
    if m.top.visible and m.navList <> invalid then
        m.top.setFocus(true)
        setNavSelectionById(m.currentNavId)

        ' Always ensure something has focus when the scene becomes visible.
        if m.focusTarget = invalid or m.focusTarget = "nav" then
            m.navList.setFocus(true)

        else if m.focusTarget = "rows" and m.rows <> invalid then
            m.rows.setFocus(true)

        else
            m.navList.setFocus(true)
        end if
    end if
end sub

sub onServerHostChanged(event as Object)
    host = event.getData()
    if host = invalid then host = ""
    host = normalizeHostInput(host)

    if host = "" then
        setConnectionState(false, "Disconnected: set server in Settings")
        return
    end if

    m.top.serverHost = host
    m.baseUrl = buildBaseUrlFromHost(host)
    startAutoConnect()
end sub

function loadServerHost() as String
    section = CreateObject("roRegistrySection", "GlitchBox")
    if section.Exists("serverHost") then
        return section.Read("serverHost")
    end if
    return ""
end function

function buildNavItemsForContext(contextId as String) as Object
    content = CreateObject("roSGNode", "ContentNode")

    addNavItem(content, "home", "Home")
    addNavItem(content, "tv", "TV Shows")
    addNavItem(content, "movies", "Movies")
    addNavItem(content, "search", "Search")
    addNavItem(content, "settings", "Settings")
    addNavItem(content, "exit", "Exit App")

    actions = getContextActions(contextId)
    for each action in actions
        addNavItem(content, action.id, action.title)
    end for

    return content
end function

function getContextActions(contextId as String) as Object
    actions = []

    if contextId = "home" then
        actions.push({ id: "shuffle_everything", title: "Shuffle Everything" })
        actions.push({ id: "shuffle_movies", title: "Shuffle Movies" })
        actions.push({ id: "shuffle_tv", title: "Shuffle TV" })
    else if contextId = "tv" then
        actions.push({ id: "shuffle_library", title: "Shuffle Library" })
        actions.push({ id: "shuffle_tv", title: "Shuffle TV" })
    else if contextId = "movies" then
        actions.push({ id: "shuffle_library", title: "Shuffle Library" })
        actions.push({ id: "shuffle_movies", title: "Shuffle Movies" })
    end if

    return actions
end function

sub refreshNavList(contextId as String)
    if m.navList = invalid then return
    m.isRefreshingNav = true
    m.navList.content = buildNavItemsForContext(contextId)
    setNavSelectionById(contextId)
    m.isRefreshingNav = false
end sub

sub addNavItem(content as Object, id as String, title as String)
    item = content.createChild("ContentNode")
    item.id = id
    item.title = title
end sub

function isNavActionId(id as String) as Boolean
    if id = invalid then return false
    return (id = "shuffle_everything" or id = "shuffle_movies" or id = "shuffle_tv" or id = "shuffle_library" or id = "shuffle_show" or id = "shuffle_season")
end function

sub onNavSelected(event as Object)
    idx = event.getData()
    if m.navList = invalid or m.navList.content = invalid then return
    if m.isRefreshingNav = true then return

    item = m.navList.content.getChild(idx)
    if item = invalid then return

    if isNavActionId(item.id) then
        handleAction(item.id)
        return
    end if

    m.currentNavId = item.id
    refreshNavList(m.currentNavId)

    ' Exit app is an explicit user action from the left rail
    if item.id = "exit" then
        if m.globalNode <> invalid then
            m.globalNode.exitApp = true
        end if
        return
    end if

    if item.id = "settings" then
        if m.top.hasField("openSettings") then m.top.openSettings = true
        if m.top.hasField("openSettingsRequested") then m.top.openSettingsRequested = true
        return
    end if

    if item.id = "search" then
        if m.top.hasField("openSearch") then m.top.openSearch = true
        if m.top.hasField("openSearchRequested") then m.top.openSearchRequested = true
        return
    end if

    ' Basic navigation filtering for TV/Movies/Home
    if item.id = "home" then
        ' If we already have a selected library, refresh it; otherwise pick first available.
        if m.selectedLibraryId = "" then
            libId = findFirstLibraryId()
            if libId <> "" then
                m.selectedLibraryId = libId
                m.top.selectedLibraryId = m.selectedLibraryId
            end if
        end if
        if m.selectedLibraryId <> "" then
            fetchMediaForLibrary(m.selectedLibraryId)
        end if
        return
    end if

    if item.id = "tv" then
        libId = findFirstLibraryIdByKind("tv")
        if libId <> "" then
            m.selectedLibraryId = libId
            m.top.selectedLibraryId = m.selectedLibraryId
            m.selectedShowKey = ""
            m.selectedSeasonKey = ""
            if m.top.hasField("openLibrary") then m.top.openLibrary = true
        else
            setConnectionState(false, "No TV library found")
        end if
        return
    end if

    if item.id = "movies" then
        libId = findFirstLibraryIdByKind("movies")
        if libId <> "" then
            m.selectedLibraryId = libId
            m.top.selectedLibraryId = m.selectedLibraryId
            m.selectedShowKey = ""
            m.selectedSeasonKey = ""
            if m.top.hasField("openLibrary") then m.top.openLibrary = true
        else
            setConnectionState(false, "No Movies library found")
        end if
        return
    end if
end sub

sub playContinueWatching()
    if m.continueWatching = invalid or m.continueWatching.Count() = 0 then
        setConnectionState(false, "No recent items to resume")
        return
    end if
    item = m.continueWatching[0]
    if item = invalid or item.media_file_id = invalid then
        setConnectionState(false, "No recent items to resume")
        return
    end if
    resumeItem = {
        id: item.media_file_id,
        title: item.title,
        poster_url: item.poster_url,
        posterUrl: item.posterUrl
    }
    openItemAutoPlay(resumeItem, [resumeItem], 0)
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

sub fetchLibraries()
    if m.baseUrl = "" then return

    setLoading(true, "Loading libraries...")

    m.librariesTask = CreateObject("roSGNode", "ApiTask")
    m.librariesTask.url = m.baseUrl + "/libraries?limit=50&offset=0"
    m.librariesTask.observeField("response", "onLibrariesResponse")
    m.librariesTask.control = "RUN"
end sub

sub checkHealth()
    if m.baseUrl = "" then return
    m.healthTask = CreateObject("roSGNode", "ApiTask")
    m.healthTask.url = m.baseUrl + "/health"
    m.healthTask.observeField("response", "onHealthResponse")
    m.healthTask.control = "RUN"
end sub

sub onHealthResponse(event as Object)
    apiTask = event.getRoSGNode()
    ' Release retained task
    m.healthTask = invalid
    if apiTask.responseCode = 200 then
        setConnectionState(true, "Server reachable")
        if m.pendingAutoConnect then
            m.pendingAutoConnect = false
            fetchLibraries()
        end if
    else
        m.pendingAutoConnect = false
        setLoading(false, "Server unreachable. Open Settings to update.")
    end if
end sub

sub fetchContinueWatching()
    userId = loadUserId()
    if userId = "" then return
    if m.baseUrl = "" then return

    m.continueTask = CreateObject("roSGNode", "ApiTask")
    m.continueTask.url = m.baseUrl + "/users/" + userId + "/continue-watching?limit=20&offset=0"
    m.continueTask.observeField("response", "onContinueWatchingResponse")
    m.continueTask.control = "RUN"
end sub

sub onContinueWatchingResponse(event as Object)
    apiTask = event.getRoSGNode()
    ' Release retained task
    m.continueTask = invalid
    if apiTask.responseCode <> 200 then return

    json = ParseJson(apiTask.response)
    if json = invalid or json.items = invalid then return

    m.continueWatching = json.items
    saveLastSync()
end sub

sub onLibrariesResponse(event as Object)
    apiTask = event.getRoSGNode()
    ' Release retained task
    m.librariesTask = invalid

    if apiTask.responseCode <> 200 then
        setLoading(false, "Connection failed (" + apiTask.responseCode.toStr() + "). Retry.")
        return
    end if

    json = ParseJson(apiTask.response)
    if json = invalid then
        setLoading(false, "Invalid server response.")
        return
    end if

    items = invalid
    if json.items <> invalid then
        items = json.items
    else if json.libraries <> invalid then
        items = json.libraries
    else if json.data <> invalid then
        items = json.data
    else if json.results <> invalid then
        items = json.results
    end if

    if items = invalid then
        setLoading(false, "Invalid server response.")
        return
    end if

    m.libraries = items
    m.top.libraries = m.libraries
    saveLastSync()
    if m.libraries <> invalid and m.libraries.Count() > 0 then
        fetchContinueWatching()
        if m.selectedLibraryId = "" then
            firstLib = m.libraries[0]
            if firstLib <> invalid and firstLib.id <> invalid then
                m.selectedLibraryId = firstLib.id.toStr()
                m.top.selectedLibraryId = m.selectedLibraryId
            end if
        end if
        fetchMediaForLibrary(m.selectedLibraryId)
    else
        setLoading(false, "No libraries found.")
    end if
end sub

sub onRowItemSelected(event as Object)
    selection = event.getData()
    if selection = invalid or selection.Count() < 2 then return

    rowIndex = selection[0]
    itemIndex = selection[1]

    rowType = getRowType(rowIndex)

    if rowType = "libraries" then
        node = getRowItemNode(rowIndex, itemIndex)
        if node <> invalid and node.id <> invalid then
            m.selectedLibraryId = node.id
            m.top.selectedLibraryId = m.selectedLibraryId
            m.selectedShowKey = ""
            m.selectedSeasonKey = ""
            if m.top.hasField("openLibrary") then m.top.openLibrary = true
        end if
        return
    end if

    if rowType = "continue" then
        node = getRowItemNode(rowIndex, itemIndex)
        if node <> invalid then
            resumePos = 0
            if node.resumePosition <> invalid then resumePos = node.resumePosition
            m.top.selectedItem = {
                id: node.id,
                title: node.title,
                poster: node.HDPosterUrl,
                url: buildPlaybackUrl(node.id),
                streamFormat: "hls",
                resumePosition: resumePos,
                queue: buildQueueForRow(rowIndex),
                queueIndex: itemIndex
            }
        end if
        return
    end if

    if rowType = "media" or rowType = "recent" then
        node = getRowItemNode(rowIndex, itemIndex)
        if node <> invalid then
            m.top.selectedItem = {
                id: node.id,
                title: node.title,
                poster: node.HDPosterUrl,
                url: buildPlaybackUrl(node.id),
                streamFormat: "hls",
                queue: buildQueueForRow(rowIndex),
                queueIndex: itemIndex
            }
        end if
        return
    end if

    if rowType = "shows" then
        if itemIndex >= 0 and itemIndex < m.tvShowKeys.Count() then
            m.selectedShowKey = m.tvShowKeys[itemIndex]
            m.selectedSeasonKey = ""
            fetchTvSeasons(m.selectedShowKey)
        end if
        return
    end if

    if rowType = "seasons" then
        if itemIndex >= 0 and itemIndex < m.tvSeasonGroups.Count() then
            m.selectedSeasonKey = m.tvSeasonGroups[itemIndex].group_key
            buildHomeRows()
        end if
        return
    end if

end sub

function buildQueueForRow(rowIndex as Integer) as Object
    queue = []
    if m.rows = invalid or m.rows.content = invalid then return queue
    rowNode = m.rows.content.getChild(rowIndex)
    if rowNode = invalid then return queue

    for i = 0 to rowNode.getChildCount() - 1
        node = rowNode.getChild(i)
        if node <> invalid then
            queue.push({
                id: node.id,
                title: node.title,
                poster: node.HDPosterUrl,
                url: buildPlaybackUrl(node.id),
                streamFormat: "hls"
            })
        end if
    end for
    return queue
end function

function buildPlaybackUrl(id as Dynamic) as String
    if m.baseUrl = "" then return ""
    if id = invalid then return ""
    return m.baseUrl + "/hls/" + id.toStr() + "/master.m3u8"
end function

sub fetchMediaForLibrary(libraryId as String)
    if m.baseUrl = "" then return
    if libraryId = invalid or libraryId = "" then
        setConnectionState(true, "Select a library to load items.")
        return
    end if

    setLoading(true, "Loading media...")

    m.mediaTask = CreateObject("roSGNode", "ApiTask")
    m.mediaTask.url = m.baseUrl + "/libraries/" + libraryId + "/media-files?limit=100&offset=0"
    m.mediaTask.observeField("response", "onMediaResponse")
    m.mediaTask.control = "RUN"
end sub

sub onMediaResponse(event as Object)
    apiTask = event.getRoSGNode()
    ' Release retained task
    m.mediaTask = invalid

    if apiTask.responseCode <> 200 then
        setLoading(false, "Media load failed (" + apiTask.responseCode.toStr() + ").")
        return
    end if

    json = ParseJson(apiTask.response)
    if json = invalid or json.items = invalid then
        setLoading(false, "Invalid media response.")
        return
    end if

    saveLastSync()

    m.mediaItems = json.items
    if isTvLibrary() then
        fetchTvShows()
    else
        buildHomeRows()
    end if
end sub

sub fetchTvShows()
    if m.selectedLibraryId = "" then
        buildHomeRows()
        return
    end if

    apiTask = CreateObject("roSGNode", "ApiTask")
    apiTask.url = m.baseUrl + "/libraries/" + m.selectedLibraryId + "/groups?prefix=tv:&limit=200&offset=0"
    apiTask.observeField("response", "onTvShowsResponse")
    apiTask.control = "RUN"
end sub

sub onTvShowsResponse(event as Object)
    apiTask = event.getRoSGNode()
    if apiTask.responseCode <> 200 then
        m.tvShowKeys = []
        m.tvShowPosters = {}
        buildHomeRows()
        return
    end if

    json = ParseJson(apiTask.response)
    if json = invalid or json.items = invalid then
        m.tvShowKeys = []
        m.tvShowPosters = {}
        buildHomeRows()
        return
    end if

    shows = []
    showPosters = {}
    seen = {}
    for each g in json.items
        if g.group_key <> invalid then
            s = parseShowKey(g.group_key)
            if s <> "" and seen[s] = invalid then
                seen[s] = true
                shows.push(s)
            end if
            if s <> "" and showPosters[s] = invalid then
                if g.poster_url <> invalid and g.poster_url <> "" then
                    showPosters[s] = normalizePosterUrl(g.poster_url)
                end if
            end if
        end if
    end for
    shows.Sort()
    m.tvShowKeys = shows
    m.tvShowPosters = showPosters
    startShowPosterFetch()

    if m.selectedShowKey <> "" then
        fetchTvSeasons(m.selectedShowKey)
    else
        m.tvSeasonGroups = []
        buildHomeRows()
    end if
end sub

sub startShowPosterFetch()
    if m.tvShowKeys = invalid then return
    m.pendingShowPosterKeys = []
    for each s in m.tvShowKeys
        m.pendingShowPosterKeys.push(s)
    end for
    m.pendingShowPosterIndex = 0
    fetchNextShowPoster()
end sub

sub fetchNextShowPoster()
    if m.pendingShowPosterKeys = invalid then return
    if m.pendingShowPosterIndex >= m.pendingShowPosterKeys.Count() then
        buildHomeRows()
        return
    end if

    showKey = m.pendingShowPosterKeys[m.pendingShowPosterIndex]
    m.pendingShowPosterIndex = m.pendingShowPosterIndex + 1
    m.currentShowPosterKey = showKey

    apiTask = CreateObject("roSGNode", "ApiTask")
    apiTask.url = m.baseUrl + "/artwork?internal_key=" + urlEncode("group_key:tv:" + showKey)
    apiTask.observeField("response", "onShowPosterResponse")
    apiTask.control = "RUN"
end sub

sub onShowPosterResponse(event as Object)
    showKey = m.currentShowPosterKey
    apiTask = event.getRoSGNode()
    if apiTask.responseCode = 200 then
        json = ParseJson(apiTask.response)
        if json <> invalid and json.item <> invalid and json.item.poster_url <> invalid then
            posterUrl = normalizePosterUrl(json.item.poster_url)
            if posterUrl <> "" then
                if m.tvShowPosters = invalid then m.tvShowPosters = {}
                m.tvShowPosters[showKey] = posterUrl
            end if
        end if
    end if

    fetchNextShowPoster()
end sub

sub fetchTvSeasons(showKey as String)
    if m.selectedLibraryId = "" or showKey = "" then
        m.tvSeasonGroups = []
        buildHomeRows()
        return
    end if

    prefix = "tv:" + showKey + ":"
    apiTask = CreateObject("roSGNode", "ApiTask")
    apiTask.url = m.baseUrl + "/libraries/" + m.selectedLibraryId + "/groups?prefix=" + urlEncode(prefix) + "&limit=200&offset=0"
    apiTask.observeField("response", "onTvSeasonsResponse")
    apiTask.control = "RUN"
end sub

sub onTvSeasonsResponse(event as Object)
    apiTask = event.getRoSGNode()
    if apiTask.responseCode <> 200 then
        m.tvSeasonGroups = []
        buildHomeRows()
        return
    end if

    json = ParseJson(apiTask.response)
    if json = invalid or json.items = invalid then
        m.tvSeasonGroups = []
        buildHomeRows()
        return
    end if

    seasons = []
    for each g in json.items
        if g.group_key <> invalid then
            seasons.push({
                group_key: g.group_key,
                media_count: g.media_count,
                poster_url: normalizePosterUrl(g.poster_url)
            })
        end if
    end for
    m.tvSeasonGroups = seasons
    if m.pendingAction = "shuffle_show" then
        m.pendingAction = ""
        shuffleShow()
        return
    end if
    buildHomeRows()
end sub

sub buildHomeRows()
    contentRoot = CreateObject("roSGNode", "ContentNode")
    m.rowTypes = []

    if m.continueWatching <> invalid and m.continueWatching.Count() > 0 then
        cwRow = contentRoot.createChild("ContentNode")
        cwRow.title = "Continue Watching"
        m.rowTypes.push("continue")

        defaultPoster = "pkg:/images/icon_side_hd.png"
        for each item in m.continueWatching
            node = cwRow.createChild("ContentNode")
            node.id = getItemId(item)
            node.title = getItemTitle(item)

            posterUrl = getPosterUrlForItem(item)
            if posterUrl <> "" and Left(posterUrl, 1) = "/" then
                posterUrl = m.baseUrl + posterUrl
            end if
            if posterUrl = "" then posterUrl = defaultPoster

            node.HDPosterUrl = posterUrl
            node.SDPosterUrl = posterUrl

            if item.position_seconds <> invalid then
                node.resumePosition = item.position_seconds
            end if
        end for
    end if

    libsRow = contentRoot.createChild("ContentNode")
    libsRow.title = "Libraries"
    m.rowTypes.push("libraries")

    defaultPoster = "pkg:/images/icon_side_hd.png"
    for each lib in m.libraries
        libNode = libsRow.createChild("ContentNode")
        if lib.id <> invalid then libNode.id = lib.id.toStr()
        if lib.name <> invalid and lib.name <> "" then
            libNode.title = lib.name
        else
            libNode.title = "Library"
        end if
        if m.selectedLibraryId <> "" and libNode.id = m.selectedLibraryId then
            libNode.title = libNode.title + " (Selected)"
        end if

        posterUrl = getLibraryPosterUrl(lib)
        if posterUrl = "" then posterUrl = defaultPoster
        libNode.HDPosterUrl = posterUrl
        libNode.SDPosterUrl = posterUrl
    end for

    if isTvLibrary() and m.tvShowKeys.Count() > 0 then
        showsRow = contentRoot.createChild("ContentNode")
        showsRow.title = "Shows"
        m.rowTypes.push("shows")
        for each s in m.tvShowKeys
            node = showsRow.createChild("ContentNode")
            node.id = s
            node.title = displayShowTitle(s)
            posterUrl = ""
            if m.tvShowPosters <> invalid then posterUrl = m.tvShowPosters[s]
            if posterUrl <> "" then
                node.HDPosterUrl = posterUrl
                node.SDPosterUrl = posterUrl
            end if
        end for
    end if

    if isTvLibrary() and m.tvSeasonGroups.Count() > 0 then
        seasonsRow = contentRoot.createChild("ContentNode")
        seasonsRow.title = "Seasons"
        m.rowTypes.push("seasons")
        for each g in m.tvSeasonGroups
            node = seasonsRow.createChild("ContentNode")
            node.id = g.group_key
            node.title = "Season " + parseSeasonKey(g.group_key)
            if g.poster_url <> invalid and g.poster_url <> "" then
                node.HDPosterUrl = g.poster_url
                node.SDPosterUrl = g.poster_url
            end if
        end for
    end if

    defaultPoster = "pkg:/images/icon_side_hd.png"

    recentItems = buildRecentlyAdded(m.mediaItems)
    if recentItems.Count() > 0 then
        recentRow = contentRoot.createChild("ContentNode")
        recentRow.title = "Recently Added"
        m.rowTypes.push("recent")

        for each item in recentItems
            node = recentRow.createChild("ContentNode")
            applyMediaNode(item, node, defaultPoster)
        end for
    end if

    mediaRow = contentRoot.createChild("ContentNode")
    mediaRow.title = "Browse"
    m.rowTypes.push("media")

    browseList = filterMediaItems()
    for each item in browseList
        node = mediaRow.createChild("ContentNode")
        applyMediaNode(item, node, defaultPoster)
    end for

    if m.rows <> invalid then
        m.rows.content = contentRoot
    end if

    setLoading(false, "Ready.")
    jumpToContinueRow()
end sub

function filterMediaItems() as Object
    if not isTvLibrary() then return m.mediaItems
    if m.mediaItems = invalid then return []

    if m.selectedSeasonKey <> "" then
        return filterByGroupKey(m.mediaItems, m.selectedSeasonKey, true)
    end if
    if m.selectedShowKey <> "" then
        prefix = "tv:" + m.selectedShowKey + ":"
        return filterByGroupKey(m.mediaItems, prefix, false)
    end if
    return m.mediaItems
end function

function filterByGroupKey(items as Object, key as String, exact as Boolean) as Object
    filtered = []
    for each it in items
        gk = it.group_key
        if gk = invalid then
            filtered.push(it)
        else if exact and gk = key then
            filtered.push(it)
        else if (not exact) and Left(gk, Len(key)) = key then
            filtered.push(it)
        end if
    end for
    return filtered
end function

sub handleAction(actionId as String)
    if actionId = "shuffle_library" then
        shuffleCurrentLibrary()
    else if actionId = "shuffle_everything" then
        shuffleEverything()
    else if actionId = "shuffle_movies" then
        shuffleByKind("movies")
    else if actionId = "shuffle_tv" then
        shuffleByKind("tv")
    else if actionId = "shuffle_show" then
        shuffleShow()
    else if actionId = "shuffle_season" then
        shuffleSeason()
    else if actionId = "play_season" then
        playSeasonInOrder()
    end if
end sub

sub shuffleCurrentLibrary()
    if m.mediaItems = invalid or m.mediaItems.Count() = 0 then
        setConnectionState(false, "No items to shuffle")
        return
    end if
    pickRandomAndOpen(m.mediaItems)
end sub

sub shuffleEverything()
    if m.libraries = invalid or m.libraries.Count() = 0 then return
    idx = Rnd(m.libraries.Count()) - 1
    if idx < 0 then idx = 0
    lib = m.libraries[idx]
    if lib = invalid or lib.id = invalid then return
    fetchMediaForShuffle(lib.id.toStr())
end sub

sub shuffleByKind(kind as String)
    candidates = []
    for each lib in m.libraries
        if libraryKind(lib) = kind then candidates.push(lib)
    end for
    if candidates.Count() = 0 then
        setConnectionState(false, "No " + kind + " libraries")
        return
    end if
    idx = Rnd(candidates.Count()) - 1
    if idx < 0 then idx = 0
    lib = candidates[idx]
    fetchMediaForShuffle(lib.id.toStr())
end sub

sub shuffleShow()
    if m.selectedShowKey = "" then
        setConnectionState(false, "Select a show first")
        return
    end if
    if m.tvSeasonGroups.Count() = 0 then
        m.pendingAction = "shuffle_show"
        fetchTvSeasons(m.selectedShowKey)
        return
    end if

    total = 0
    for each g in m.tvSeasonGroups
        total = total + g.media_count
    end for
    if total <= 0 then
        setConnectionState(false, "No episodes found")
        return
    end if
    r = Rnd(total)
    acc = 0
    chosen = m.tvSeasonGroups[0]
    for each g in m.tvSeasonGroups
        acc = acc + g.media_count
        if r <= acc then
            chosen = g
            exit for
        end if
    end for
    fetchMediaForGroup(chosen.group_key, "shuffle_season_pick")
end sub

sub shuffleSeason()
    if m.selectedSeasonKey = "" then
        setConnectionState(false, "Select a season first")
        return
    end if
    fetchMediaForGroup(m.selectedSeasonKey, "shuffle")
end sub

sub playSeasonInOrder()
    if m.selectedSeasonKey = "" then
        setConnectionState(false, "Select a season first")
        return
    end if
    fetchMediaForGroup(m.selectedSeasonKey, "ordered")
end sub

sub fetchMediaForGroup(groupKey as String, mode as String)
    if m.baseUrl = "" then return
    apiTask = CreateObject("roSGNode", "ApiTask")
    apiTask.url = m.baseUrl + "/libraries/" + m.selectedLibraryId + "/media-files?limit=500&offset=0&group_key=" + urlEncode(groupKey) + "&order=title_asc"
    apiTask.observeField("response", "onGroupMediaResponse")
    apiTask.mode = mode
    apiTask.control = "RUN"
end sub

sub onGroupMediaResponse(event as Object)
    apiTask = event.getRoSGNode()
    if apiTask.responseCode <> 200 then
        setConnectionState(false, "Group load failed")
        return
    end if
    json = ParseJson(apiTask.response)
    if json = invalid or json.items = invalid then
        setConnectionState(false, "Group response invalid")
        return
    end if
    mode = apiTask.mode
    items = json.items
    if items.Count() = 0 then
        setConnectionState(false, "No items in group")
        return
    end if
    if mode = "ordered" then
        openQueueFromItems(items, 0)
    else
        pickRandomAndOpen(items)
    end if
end sub

sub fetchMediaForShuffle(libraryId as String)
    if m.baseUrl = "" then return
    apiTask = CreateObject("roSGNode", "ApiTask")
    apiTask.url = m.baseUrl + "/libraries/" + libraryId + "/media-files?limit=500&offset=0"
    apiTask.observeField("response", "onShuffleMediaResponse")
    apiTask.control = "RUN"
end sub

sub onShuffleMediaResponse(event as Object)
    apiTask = event.getRoSGNode()
    if apiTask.responseCode <> 200 then
        setConnectionState(false, "Shuffle load failed")
        return
    end if
    json = ParseJson(apiTask.response)
    if json = invalid or json.items = invalid then
        setConnectionState(false, "Shuffle response invalid")
        return
    end if
    pickRandomAndOpen(json.items)
end sub

sub pickRandomAndOpen(items as Object)
    if items = invalid or items.Count() = 0 then return
    idx = Rnd(items.Count()) - 1
    if idx < 0 then idx = 0
    it = items[idx]
    openItemAutoPlay(it, [it], 0)
end sub

sub openQueueFromItems(items as Object, startIndex as Integer)
    queue = []
    for each it in items
        id = getItemId(it)
        title = getItemTitle(it)
        queue.push({
            id: id,
            title: title,
            poster: getPosterUrlForItem(it),
            url: buildPlaybackUrl(id),
            streamFormat: "hls"
        })
    end for
    openItemAutoPlay(items[startIndex], queue, startIndex)
end sub

sub openItem(item as Object, queue as Object, index as Integer)
    if item = invalid then return
    id = getItemId(item)
    title = getItemTitle(item)
    posterUrl = getPosterUrlForItem(item)
    m.top.selectedItem = {
        id: id,
        title: title,
        poster: posterUrl,
        url: buildPlaybackUrl(id),
        streamFormat: "hls",
        queue: queue,
        queueIndex: index
    }
end sub

sub openItemAutoPlay(item as Object, queue as Object, index as Integer)
    if item = invalid then return
    id = getItemId(item)
    title = getItemTitle(item)
    posterUrl = getPosterUrlForItem(item)
    m.top.playNow = {
        id: id,
        title: title,
        poster: posterUrl,
        url: buildPlaybackUrl(id),
        streamFormat: "hls",
        queue: queue,
        queueIndex: index
    }
end sub

function getPosterUrlForItem(item as Object) as String
    posterUrl = ""
    if item.poster_url <> invalid and item.poster_url <> "" then
        posterUrl = item.poster_url
    else if item.posterUrl <> invalid and item.posterUrl <> "" then
        posterUrl = item.posterUrl
    else if item.poster_path <> invalid and item.poster_path <> "" then
        posterUrl = item.poster_path
    else if item.thumb_url <> invalid and item.thumb_url <> "" then
        posterUrl = item.thumb_url
    else if item.artwork_url <> invalid and item.artwork_url <> "" then
        posterUrl = item.artwork_url
    end if
    if posterUrl <> "" and Left(posterUrl, 1) = "/" then
        posterUrl = m.baseUrl + posterUrl
    end if
    if posterUrl = "" then posterUrl = "pkg:/images/icon_side_hd.png"
    return posterUrl
end function

function normalizePosterUrl(url as Dynamic) as String
    posterUrl = ""
    if url <> invalid then posterUrl = url.toStr()
    if posterUrl <> "" and Left(posterUrl, 1) = "/" then
        posterUrl = m.baseUrl + posterUrl
    end if
    return posterUrl
end function

function getLibraryPosterUrl(lib as Object) as String
    if lib = invalid then return ""
    posterUrl = ""

    if lib.poster_url <> invalid and lib.poster_url <> "" then
        posterUrl = lib.poster_url
    else if lib.posterUrl <> invalid and lib.posterUrl <> "" then
        posterUrl = lib.posterUrl
    else if lib.poster_path <> invalid and lib.poster_path <> "" then
        posterUrl = lib.poster_path
    else if lib.thumb_url <> invalid and lib.thumb_url <> "" then
        posterUrl = lib.thumb_url
    else if lib.thumbUrl <> invalid and lib.thumbUrl <> "" then
        posterUrl = lib.thumbUrl
    else if lib.artwork_url <> invalid and lib.artwork_url <> "" then
        posterUrl = lib.artwork_url
    else if lib.artworkUrl <> invalid and lib.artworkUrl <> "" then
        posterUrl = lib.artworkUrl
    else if lib.cover_url <> invalid and lib.cover_url <> "" then
        posterUrl = lib.cover_url
    else if lib.coverUrl <> invalid and lib.coverUrl <> "" then
        posterUrl = lib.coverUrl
    else if lib.image_url <> invalid and lib.image_url <> "" then
        posterUrl = lib.image_url
    else if lib.imageUrl <> invalid and lib.imageUrl <> "" then
        posterUrl = lib.imageUrl
    else if lib.image <> invalid and lib.image <> "" then
        posterUrl = lib.image
    else if lib.icon_url <> invalid and lib.icon_url <> "" then
        posterUrl = lib.icon_url
    else if lib.iconUrl <> invalid and lib.iconUrl <> "" then
        posterUrl = lib.iconUrl
    else if lib.poster <> invalid and lib.poster <> "" then
        posterUrl = lib.poster
    else if lib.cover <> invalid and lib.cover <> "" then
        posterUrl = lib.cover
    end if

    if posterUrl <> "" and Left(posterUrl, 1) = "/" then
        posterUrl = m.baseUrl + posterUrl
    end if
    return posterUrl
end function

function getItemId(item as Object) as String
    if item = invalid then return ""
    if item.media_file_id <> invalid then return item.media_file_id.toStr()
    if item.id <> invalid then return item.id.toStr()
    return ""
end function

function getItemTitle(item as Object) as String
    if item = invalid then return "Untitled"
    if item.title <> invalid and item.title <> "" then return item.title
    if item.display_title <> invalid and item.display_title <> "" then return item.display_title
    if item.name <> invalid and item.name <> "" then return item.name
    if item.media_title <> invalid and item.media_title <> "" then return item.media_title
    if item.file_path <> invalid and item.file_path <> "" then
        derived = titleFromPath(item.file_path)
        if derived <> "" then return derived
    end if
    return "Untitled"
end function

function titleFromPath(path as String) as String
    if path = invalid or path = "" then return ""
    p = path
    parts = p.Split("/")
    if parts <> invalid and parts.Count() > 0 then
        p = parts[parts.Count() - 1]
    end if
    if p = invalid then return ""
    extParts = p.Split(".")
    if extParts <> invalid and extParts.Count() > 1 then
        p = extParts[0]
    end if
    p = p.Replace("_", " ").Replace(".", " ").Replace("-", " ")
    return p.Trim()
end function

function parseShowKey(gk as String) as String
    if gk = invalid then return ""
    if Left(gk, 3) <> "tv:" then return ""
    parts = gk.Split(":")
    if parts = invalid or parts.Count() < 2 then return ""
    return parts[1]
end function

function displayShowTitle(showKey as String) as String
    if showKey = invalid then return ""
    t = showKey
    t = t.Replace("-", " ").Replace("_", " ").Replace(".", " ")
    return t.Trim()
end function

function parseSeasonKey(gk as String) as String
    if gk = invalid then return ""
    parts = gk.Split(":")
    if parts = invalid or parts.Count() < 3 then return ""
    seasonPart = parts[2]
    if seasonPart = invalid or Len(seasonPart) < 2 then return ""
    if Left(seasonPart, 1) <> "s" then return ""
    return seasonPart.Mid(2)
end function


' Helper function to get a library object by its id
function getLibraryById(id as String) as Object
    if id = invalid or id = "" then return invalid
    if m.libraries = invalid then return invalid

    for each lib in m.libraries
        if lib <> invalid and lib.id <> invalid and lib.id.toStr() = id then
            return lib
        end if
    end for

    return invalid
end function

function isTvLibrary() as Boolean
    lib = getLibraryById(m.selectedLibraryId)
    if lib = invalid then return false
    return libraryKind(lib) = "tv"
end function

function libraryKind(lib as Object) as String
    if lib = invalid then return "unknown"
    name = ""
    if lib.name <> invalid then name = LCase(lib.name)
    t = ""
    if lib.type <> invalid then t = LCase(lib.type)

    if Instr(1, name, "tv") > 0 or Instr(1, name, "show") > 0 or Instr(1, name, "series") > 0 or Instr(1, name, "television") > 0 then return "tv"
    if Instr(1, t, "tv") > 0 or Instr(1, t, "show") > 0 then return "tv"
    if Instr(1, name, "movie") > 0 or Instr(1, t, "movie") > 0 then return "movies"
    return "unknown"
end function

function urlEncode(s as String) as String
    t = CreateObject("roUrlTransfer")
    return t.Escape(s)
end function

sub saveLastSync()
    section = CreateObject("roRegistrySection", "GlitchBox")
    stamp = currentTimestamp()
    section.Write("lastSync", stamp)
    section.Flush()
    m.top.lastSync = stamp
end sub

function currentTimestamp() as String
    dt = CreateObject("roDateTime")
    ' Most compatible: avoid AsDateString/AsTimeString which are missing on some firmwares
    return dt.AsSeconds().ToStr()
end function

sub jumpToContinueRow()
    if m.rows = invalid then return
    idx = getRowTypeIndex("continue")
    if idx < 0 then return
    m.rows.jumpToRowItem = [idx, 0]
end sub

function getRowTypeIndex(rowType as String) as Integer
    if m.rowTypes = invalid then return -1
    for i = 0 to m.rowTypes.Count() - 1
        if m.rowTypes[i] = rowType then return i
    end for
    return -1
end function

function loadUserId() as String
    section = CreateObject("roRegistrySection", "GlitchBox")
    if section.Exists("userId") then
        return section.Read("userId")
    end if
    return ""
end function

function buildRecentlyAdded(items as Object) as Object
    recent = []
    if items = invalid then return recent

    maxItems = 12
    count = items.Count()
    if count > maxItems then count = maxItems

    for i = 0 to count - 1
        recent.push(items[i])
    end for

    return recent
end function

sub applyMediaNode(item as Object, node as Object, defaultPoster as String)
    if item = invalid or node = invalid then return

    node.id = getItemId(item)
    node.title = getItemTitle(item)

    posterUrl = getPosterUrlForItem(item)

    if posterUrl <> "" and Left(posterUrl, 1) = "/" then
        posterUrl = m.baseUrl + posterUrl
    end if
    if posterUrl = "" then posterUrl = defaultPoster

    node.HDPosterUrl = posterUrl
    node.SDPosterUrl = posterUrl
end sub

sub setConnectionState(isConnected as Boolean, msg as String)
    if m.connectionBadge <> invalid then
        m.connectionBadge.visible = isConnected
    end if
    if m.status <> invalid and msg <> invalid and msg <> "" then
        m.status.text = msg
    end if
end sub

sub setLoading(isLoading as Boolean, msg as String)
    setConnectionState(not isLoading, msg)
    if m.loadingOverlay <> invalid then
        m.loadingOverlay.message = msg
        m.loadingOverlay.visible = isLoading
    end if
end sub

sub startAutoConnect()
    if m.baseUrl = "" then return
    m.pendingAutoConnect = true
    setLoading(true, "Testing connection...")
    checkHealth()
end sub

sub setNavSelectionById(id as String)
    if m.navList = invalid or m.navList.content = invalid then return

    for i = 0 to m.navList.content.getChildCount() - 1
        item = m.navList.content.getChild(i)
        if item <> invalid and item.id = id then
            m.navList.jumpToItem = i
            exit for
        end if
    end for
end sub

function findFirstLibraryId() as String
    if m.libraries = invalid or m.libraries.Count() = 0 then return ""
    lib = m.libraries[0]
    if lib = invalid or lib.id = invalid then return ""
    return lib.id.toStr()
end function

function findFirstLibraryIdByKind(kind as String) as String
    if m.libraries = invalid or m.libraries.Count() = 0 then return ""
    for each lib in m.libraries
        if libraryKind(lib) = kind then
            if lib <> invalid and lib.id <> invalid then return lib.id.toStr()
        end if
    end for
    return ""
end function

function getRowType(rowIndex as Integer) as String
    if m.rowTypes = invalid or rowIndex < 0 or rowIndex >= m.rowTypes.Count() then return ""
    return m.rowTypes[rowIndex]
end function

function getRowItemNode(rowIndex as Integer, itemIndex as Integer) as Object
    if m.rows = invalid or m.rows.content = invalid then return invalid
    rowNode = m.rows.content.getChild(rowIndex)
    if rowNode = invalid then return invalid
    return rowNode.getChild(itemIndex)
end function

function onKeyEvent(key as String, press as Boolean) as Boolean
    if press = false then return false
    ' If disconnected, allow moving focus to the Retry button
    ' Move between left nav and main rows
    if key = "right" and m.navList <> invalid and m.navList.hasFocus() then
        if m.rows <> invalid then
            m.rows.setFocus(true)
            m.focusTarget = "rows"
            return true
        end if
    end if

    if key = "left" and m.rows <> invalid and m.rows.hasFocus() then
        if m.navList <> invalid then
            m.navList.setFocus(true)
            m.focusTarget = "nav"
            return true
        end if
    end if

    return false
end function
