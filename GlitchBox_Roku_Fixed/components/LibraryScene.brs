sub init()
    m.actions = m.top.findNode("actions")
    m.rows = m.top.findNode("rows")
    m.title = m.top.findNode("title")
    m.status = m.top.findNode("status")
    m.railTitle = m.top.findNode("railTitle")

    m.baseUrl = ""
    m.mediaItems = []
    m.rowTypes = []
    m.tvShowKeys = []
    m.tvShowPosters = {}
    m.tvSeasonGroups = []
    m.selectedShowKey = ""
    m.selectedSeasonKey = ""
    m.focusTarget = "actions"

    if m.actions <> invalid then
        m.actions.observeField("itemSelected", "onActionSelected")
    end if

    if m.rows <> invalid then
        m.rows.observeField("rowItemSelected", "onRowItemSelected")
    end if

    if m.top.hasField("libraryId") then m.top.observeField("libraryId", "onLibraryChanged")
    if m.top.hasField("libraryName") then m.top.observeField("libraryName", "onLibraryChanged")
    if m.top.hasField("libraryKind") then m.top.observeField("libraryKind", "onLibraryChanged")
    if m.top.hasField("serverHost") then m.top.observeField("serverHost", "onServerHostChanged")
    if m.top.hasField("visible") then m.top.observeField("visible", "onVisibleChanged")

    refreshTitles()
    refreshActions()
end sub

sub onVisibleChanged(event as Object)
    if m.top.visible <> true then return

    refreshTitles()
    refreshActions()
    fetchLibraryContent()

    if m.actions <> invalid then
        m.actions.setFocus(true)
        m.focusTarget = "actions"
    end if
end sub

sub onLibraryChanged(event as Object)
    refreshTitles()
    refreshActions()
    fetchLibraryContent()
end sub

sub onServerHostChanged(event as Object)
    refreshTitles()
    fetchLibraryContent()
end sub

sub refreshTitles()
    name = ""
    if m.top.hasField("libraryName") then name = m.top.libraryName
    if name = invalid or name = "" then name = "Library"
    if m.title <> invalid then m.title.text = name
    if m.railTitle <> invalid then m.railTitle.text = name
end sub

sub refreshActions()
    if m.actions = invalid then return
    buttons = []

    buttons.push({ id: "shuffle_library", title: "Shuffle Library" })

    if getLibraryKind() = "tv" then
        if m.selectedShowKey <> "" then
            buttons.push({ id: "shuffle_show", title: "Shuffle Series" })
        end if
        if m.selectedSeasonKey <> "" then
            buttons.push({ id: "shuffle_season", title: "Shuffle Season" })
        end if
    end if

    buttons.push({ id: "back", title: "Back" })

    content = CreateObject("roSGNode", "ContentNode")
    for each b in buttons
        node = content.createChild("ContentNode")
        node.id = b.id
        node.title = b.title
    end for
    m.actions.content = content
end sub

sub onActionSelected(event as Object)
    idx = event.getData()
    if m.actions = invalid or m.actions.content = invalid then return
    node = m.actions.content.getChild(idx)
    if node = invalid or node.id = invalid then return

    if node.id = "back" then
        m.top.backRequested = true
        return
    end if

    if node.id = "shuffle_library" then
        shuffleLibrary()
        return
    end if

    if node.id = "shuffle_show" then
        shuffleShow()
        return
    end if

    if node.id = "shuffle_season" then
        shuffleSeason()
        return
    end if
end sub

sub fetchLibraryContent()
    host = ""
    if m.top.hasField("serverHost") then host = m.top.serverHost
    host = normalizeHostInput(host)
    if host = "" then
        setStatus("Set server in Settings")
        return
    end if
    m.baseUrl = buildBaseUrlFromHost(host)

    libId = ""
    if m.top.hasField("libraryId") then libId = m.top.libraryId
    if libId = invalid or libId = "" then
        setStatus("No library selected")
        return
    end if

    setStatus("Loading library...")
    apiTask = CreateObject("roSGNode", "ApiTask")
    apiTask.url = m.baseUrl + "/libraries/" + libId + "/media-files?limit=200&offset=0"
    apiTask.observeField("response", "onMediaResponse")
    apiTask.control = "RUN"
end sub

sub onMediaResponse(event as Object)
    apiTask = event.getRoSGNode()
    if apiTask.responseCode <> 200 then
        setStatus("Library load failed (" + apiTask.responseCode.toStr() + ")")
        return
    end if

    json = ParseJson(apiTask.response)
    if json = invalid or json.items = invalid then
        setStatus("Invalid library response")
        return
    end if

    m.mediaItems = json.items
    m.selectedShowKey = ""
    m.selectedSeasonKey = ""
    m.tvShowKeys = []
    m.tvShowPosters = {}
    m.tvSeasonGroups = []

    if getLibraryKind() = "tv" then
        fetchTvShows()
    else
        buildRows()
    end if
end sub

sub fetchTvShows()
    libId = m.top.libraryId
    if libId = invalid or libId = "" then
        buildRows()
        return
    end if

    apiTask = CreateObject("roSGNode", "ApiTask")
    apiTask.url = m.baseUrl + "/libraries/" + libId + "/groups?prefix=tv:&limit=200&offset=0"
    apiTask.observeField("response", "onTvShowsResponse")
    apiTask.control = "RUN"
end sub

sub onTvShowsResponse(event as Object)
    apiTask = event.getRoSGNode()
    if apiTask.responseCode <> 200 then
        buildRows()
        return
    end if

    json = ParseJson(apiTask.response)
    if json = invalid or json.items = invalid then
        buildRows()
        return
    end if

    shows = []
    showPosters = {}
    seen = {}
    for each g in json.items
        if g.group_key <> invalid then
            showKey = parseShowKey(g.group_key)
            if showKey <> "" and seen[showKey] = invalid then
                shows.push(showKey)
                seen[showKey] = true
            end if
            if showKey <> "" and showPosters[showKey] = invalid then
                if g.poster_url <> invalid and g.poster_url <> "" then
                    showPosters[showKey] = normalizePosterUrl(g.poster_url)
                end if
            end if
        end if
    end for

    m.tvShowKeys = shows
    m.tvShowPosters = showPosters
    startShowPosterFetch()
    buildRows()
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
        buildRows()
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
    if showKey = "" then
        buildRows()
        return
    end if

    apiTask = CreateObject("roSGNode", "ApiTask")
    apiTask.url = m.baseUrl + "/libraries/" + m.top.libraryId + "/groups?prefix=" + urlEncode("tv:" + showKey + ":") + "&limit=200&offset=0"
    apiTask.observeField("response", "onTvSeasonsResponse")
    apiTask.control = "RUN"
end sub

sub onTvSeasonsResponse(event as Object)
    apiTask = event.getRoSGNode()
    if apiTask.responseCode <> 200 then
        m.tvSeasonGroups = []
        buildRows()
        return
    end if

    json = ParseJson(apiTask.response)
    if json = invalid or json.items = invalid then
        m.tvSeasonGroups = []
        buildRows()
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
    buildRows()
end sub

sub buildRows()
    contentRoot = CreateObject("roSGNode", "ContentNode")
    m.rowTypes = []

    if getLibraryKind() = "tv" and m.tvShowKeys.Count() > 0 then
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

    if getLibraryKind() = "tv" and m.tvSeasonGroups.Count() > 0 then
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

    if not (getLibraryKind() = "tv" and m.selectedShowKey <> "" and m.selectedSeasonKey = "") then
        mediaRow = contentRoot.createChild("ContentNode")
        if getLibraryKind() = "tv" and m.selectedSeasonKey <> "" then
            mediaRow.title = "Episodes"
        else
            mediaRow.title = "Browse"
        end if
        m.rowTypes.push("media")

        browseList = filterMediaItems()
        for each item in browseList
            node = mediaRow.createChild("ContentNode")
            applyMediaNode(item, node, defaultPoster)
        end for
    end if

    if m.rows <> invalid then
        m.rows.content = contentRoot
    end if

    setStatus("Ready")
end sub

sub onRowItemSelected(event as Object)
    selection = event.getData()
    if selection = invalid or selection.Count() < 2 then return

    rowIndex = selection[0]
    itemIndex = selection[1]
    rowType = getRowType(rowIndex)

    if rowType = "shows" then
        if itemIndex >= 0 and itemIndex < m.tvShowKeys.Count() then
            m.selectedShowKey = m.tvShowKeys[itemIndex]
            m.selectedSeasonKey = ""
            refreshActions()
            fetchTvSeasons(m.selectedShowKey)
        end if
        return
    end if

    if rowType = "seasons" then
        if itemIndex >= 0 and itemIndex < m.tvSeasonGroups.Count() then
            m.selectedSeasonKey = m.tvSeasonGroups[itemIndex].group_key
            refreshActions()
            buildRows()
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
end sub

function onKeyEvent(key as String, press as Boolean) as Boolean
    if press = false then return false

    if key = "left" and m.rows <> invalid and m.rows.hasFocus() then
        if m.actions <> invalid then
            m.actions.setFocus(true)
            m.focusTarget = "actions"
            return true
        end if
    end if

    if key = "right" and m.actions <> invalid and m.actions.hasFocus() then
        if m.rows <> invalid then
            m.rows.setFocus(true)
            m.focusTarget = "rows"
            return true
        end if
    end if

    if key = "back" then
        m.top.backRequested = true
        return true
    end if

    return false
end function

sub shuffleLibrary()
    if m.mediaItems = invalid or m.mediaItems.Count() = 0 then
        setStatus("No items to shuffle")
        return
    end if
    pickRandomAndPlay(m.mediaItems)
end sub

sub shuffleShow()
    if m.selectedShowKey = "" then
        setStatus("Select a show first")
        return
    end if
    if m.tvSeasonGroups.Count() = 0 then
        fetchTvSeasons(m.selectedShowKey)
        return
    end if

    total = 0
    for each g in m.tvSeasonGroups
        total = total + g.media_count
    end for
    if total <= 0 then
        setStatus("No episodes found")
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
    fetchMediaForGroup(chosen.group_key)
end sub

sub shuffleSeason()
    if m.selectedSeasonKey = "" then
        setStatus("Select a season first")
        return
    end if
    fetchMediaForGroup(m.selectedSeasonKey)
end sub

sub fetchMediaForGroup(groupKey as String)
    if m.baseUrl = "" then return
    apiTask = CreateObject("roSGNode", "ApiTask")
    apiTask.url = m.baseUrl + "/libraries/" + m.top.libraryId + "/media-files?limit=500&offset=0&group_key=" + urlEncode(groupKey)
    apiTask.observeField("response", "onGroupMediaResponse")
    apiTask.control = "RUN"
end sub

sub onGroupMediaResponse(event as Object)
    apiTask = event.getRoSGNode()
    if apiTask.responseCode <> 200 then
        setStatus("Shuffle load failed")
        return
    end if
    json = ParseJson(apiTask.response)
    if json = invalid or json.items = invalid then
        setStatus("Shuffle response invalid")
        return
    end if
    pickRandomAndPlay(json.items)
end sub

sub pickRandomAndPlay(items as Object)
    if items = invalid or items.Count() = 0 then return
    queue = buildQueueFromItems(items)
    if queue.Count() = 0 then return
    openItemAutoPlay(queue[0], queue, 0)
end sub

sub openItem(item as Object)
    if item = invalid then return
    posterUrl = getPosterUrlForItem(item)
    m.top.selectedItem = {
        id: getItemId(item),
        title: getItemTitle(item),
        poster: posterUrl,
        url: buildPlaybackUrl(getItemId(item)),
        streamFormat: "hls"
    }
end sub

sub openItemAutoPlay(item as Object, queue as Object, index as Integer)
    if item = invalid then return
    posterUrl = item.poster
    if posterUrl = invalid or posterUrl = "" then posterUrl = getPosterUrlForItem(item)
    m.top.playNow = {
        id: item.id,
        title: item.title,
        poster: posterUrl,
        url: item.url,
        streamFormat: "hls",
        queue: queue,
        queueIndex: index
    }
end sub

function buildQueueFromItems(items as Object) as Object
    queue = []
    if items = invalid then return queue

    ' Build a shuffle queue with stable metadata for skip/prev.
    indices = []
    for i = 0 to items.Count() - 1
        indices.push(i)
    end for

    for i = indices.Count() - 1 to 1 step -1
        j = Rnd(i + 1) - 1
        if j < 0 then j = 0
        temp = indices[i]
        indices[i] = indices[j]
        indices[j] = temp
    end for

    for each idx in indices
        it = items[idx]
        id = getItemId(it)
        if id = "" then continue for
        queue.push({
            id: id,
            title: getItemTitle(it),
            poster: getPosterUrlForItem(it),
            url: buildPlaybackUrl(id),
            streamFormat: "hls"
        })
    end for

    return queue
end function

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

function buildPlaybackUrl(id as Dynamic) as String
    if m.baseUrl = "" then return ""
    if id = invalid then return ""
    return m.baseUrl + "/hls/" + id.toStr() + "/master.m3u8"
end function

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

function getLibraryKind() as String
    kind = ""
    if m.top.hasField("libraryKind") then kind = m.top.libraryKind
    if kind = invalid then kind = ""
    return LCase(kind)
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

function filterMediaItems() as Object
    if getLibraryKind() <> "tv" then return m.mediaItems
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
    t = t.Replace("-", " ")
    t = t.Replace("_", " ")
    t = t.Replace(".", " ")
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

sub setStatus(msg as String)
    if m.status <> invalid then m.status.text = msg
end sub
