sub init()
    m.video = m.top.findNode("video")
    m.actionOverlay = m.top.findNode("actionOverlay")
    m.actionBar = m.top.findNode("actionBar")
    m.titleOverlay = m.top.findNode("titleOverlay")
    m.titleLabel = m.top.findNode("titleLabel")
    m.titleTimer = m.top.findNode("titleTimer")
    m.playerStatus = m.top.findNode("playerStatus")
    m.playerStatusLabel = m.top.findNode("playerStatusLabel")
    m.nowPlayingOverlay = m.top.findNode("nowPlayingOverlay")
    m.nowPlayingLabel = m.top.findNode("nowPlayingLabel")
    m.nowPlayingTime = m.top.findNode("nowPlayingTime")
    m.errorOverlay = m.top.findNode("errorOverlay")
    m.errorLabel = m.top.findNode("errorLabel")
    m.errorActions = m.top.findNode("errorActions")
    m.nowPlayingTimer = m.top.findNode("nowPlayingTimer")
    m.actionTimer = m.top.findNode("actionTimer")
    m.resumeOverlay = m.top.findNode("resumeOverlay")
    m.resumeActions = m.top.findNode("resumeActions")
    m.resumeLabel = m.top.findNode("resumeLabel")
    m.queueOverlay = m.top.findNode("queueOverlay")
    m.queuePrev = m.top.findNode("queuePrev")
    m.queueNow = m.top.findNode("queueNow")
    m.queueNext = m.top.findNode("queueNext")
    m.pendingContent = invalid
    m.pendingResumePos = 0
    m.currentItemId = ""

    if m.actionBar <> invalid then
        m.actionBar.buttons = ["Play/Pause", "Play From Start", "Previous", "Skip Next", "Queue", "Mark Watched", "Stop"]
        m.actionBar.observeField("buttonSelected", "onActionSelected")
    end if

    if m.titleTimer <> invalid then
        m.titleTimer.observeField("fire", "onTitleTimerFire")
    end if
    if m.nowPlayingTimer <> invalid then
        m.nowPlayingTimer.observeField("fire", "onNowPlayingTimerFire")
    end if
    if m.actionTimer <> invalid then
        m.actionTimer.observeField("fire", "onActionTimerFire")
    end if

    if m.video <> invalid then
        m.video.observeField("state", "onVideoState")
        m.video.observeField("position", "onVideoPosition")
        m.video.observeField("duration", "onVideoPosition")
        ' Ensure Video owns focus so left/right/OK behave predictably
        m.video.setFocus(true)
    end if

    m.top.observeField("playbackItem", "onPlaybackItemChanged")

    if m.errorActions <> invalid then
        m.errorActions.buttons = ["Retry", "Back"]
        m.errorActions.observeField("buttonSelected", "onErrorActionSelected")
    end if

    if m.resumeActions <> invalid then
        m.resumeActions.buttons = ["Resume", "Start Over"]
        m.resumeActions.observeField("buttonSelected", "onResumeActionSelected")
    end if
end sub

sub onPlaybackItemChanged()
    item = m.top.playbackItem
    if item = invalid then return

    if m.video = invalid then return
    syncQueueFromItem(item)

    if item.url <> invalid and item.url <> "" then
        content = CreateObject("roSGNode", "ContentNode")
        content.url = item.url
        if item.title <> invalid then content.title = item.title
        if item.streamFormat <> invalid then content.streamFormat = item.streamFormat
        m.currentItemId = ""
        if item.id <> invalid then m.currentItemId = item.id.toStr()

        if item.resumePosition <> invalid and val(item.resumePosition) > 0 then
            m.video.content = content
            m.video.setFocus(true)
            m.video.seek = val(item.resumePosition)
            m.video.control = "play"
            showTitleOverlay(item)
            showNowPlaying(item)
            setErrorOverlay(false, "")
        else
            progress = ProgressService_Load(m.currentItemId)
            if progress <> invalid and progress.position > 0 then
                m.pendingContent = content
                m.pendingResumePos = progress.position
                showResumeOverlay(item, progress.position)
            else
                m.video.content = content
                m.video.setFocus(true)
                m.video.control = "play"
                showTitleOverlay(item)
                showNowPlaying(item)
                setErrorOverlay(false, "")
            end if
        end if

        if m.queueOverlay <> invalid and m.queueOverlay.visible then
            updateQueueOverlay()
        end if
    else
        print "PlayerScene: missing item.url for playback"
    end if
end sub

sub onActionSelected(event as Object)
    idx = event.getData()
    if idx = 0 then
        togglePlayPause()
    else if idx = 1 then
        playFromStart()
    else if idx = 2 then
        skipQueue(-1)
    else if idx = 3 then
        skipQueue(1)
    else if idx = 4 then
        showQueueOverlay(not m.queueOverlay.visible)
    else if idx = 5 then
        markWatched()
    else if idx = 6 then
        stopPlayback()
    end if
    resetActionAutoHide()
end sub

sub syncQueueFromItem(item as Object)
    if item = invalid then return
    if item.queue <> invalid then
        m.top.queue = item.queue
    end if
    if item.queueIndex <> invalid then
        m.top.queueIndex = item.queueIndex
    end if
    if m.queueOverlay <> invalid and m.queueOverlay.visible then
        updateQueueOverlay()
    end if
end sub

sub skipQueue(delta as Integer)
    if m.top.queue = invalid or m.top.queueIndex = invalid then return
    idx = m.top.queueIndex + delta
    if idx < 0 or idx >= m.top.queue.Count() then return
    nextItem = m.top.queue[idx]
    if nextItem = invalid then return

    payload = {
        id: nextItem.id,
        title: nextItem.title,
        poster: nextItem.poster,
        url: nextItem.url,
        streamFormat: nextItem.streamFormat,
        queue: m.top.queue,
        queueIndex: idx
    }
    m.top.playbackItem = payload
end sub

sub togglePlayPause()
    if m.video = invalid then return
    if m.video.state = "playing" then
        m.video.control = "pause"
    else
        m.video.control = "resume"
    end if
end sub

sub stopPlayback()
    if m.video = invalid then return
    saveProgress()
    m.video.control = "stop"
end sub

function onKeyEvent(key as String, press as Boolean) as Boolean
    if not press then return false

    if key = "down" then
        showNowPlaying(m.top.playbackItem)
        showActions(true)
        return true
    end if

    if key = "up" then
        showNowPlaying(m.top.playbackItem)
        return true
    end if

    if key = "back" then
        if m.actionOverlay <> invalid and m.actionOverlay.visible then
            showActions(false)
            return true
        end if
        if m.errorOverlay <> invalid and m.errorOverlay.visible then
            setErrorOverlay(false, "")
            return true
        end if
        if m.resumeOverlay <> invalid and m.resumeOverlay.visible then
            hideResumeOverlay()
            return true
        end if
        if m.queueOverlay <> invalid and m.queueOverlay.visible then
            showQueueOverlay(false)
            return true
        end if
        stopPlayback()
        m.top.backRequested = true
        return true
    end if

    if key = "OK" then
        showNowPlaying(m.top.playbackItem)
        if m.actionOverlay <> invalid and m.actionOverlay.visible then
            resetActionAutoHide()
            return true
        end if
    end if

    if key = "*" then
        if m.queueOverlay <> invalid then
            showQueueOverlay(not m.queueOverlay.visible)
            return true
        end if
    end if

    if m.actionOverlay <> invalid and m.actionOverlay.visible then
        if key = "left" or key = "right" then
            resetActionAutoHide()
            return false
        end if
    else
        if key = "left" then
            seekBy(-10)
            showNowPlaying(m.top.playbackItem)
            return true
        else if key = "right" then
            seekBy(10)
            showNowPlaying(m.top.playbackItem)
            return true
        end if
    end if

    return false
end function

sub onVideoState(event as Object)
    state = event.getData()

    if state = "buffering" then
        setPlayerStatus(true, "Buffering...")
    else if state = "error" then
        setPlayerStatus(true, "Playback error")
        setErrorOverlay(true, "Playback error")
        saveProgress()
    else
        setPlayerStatus(false, "")
        setErrorOverlay(false, "")
    end if

    if state = "finished" then
        ProgressService_Clear(m.currentItemId)
        postProgress(true)
    end if
end sub

sub seekBy(secondsDelta as Integer)
    if m.video = invalid then return
    currentPos = m.video.position
    target = currentPos + secondsDelta
    if target < 0 then target = 0
    m.video.seek = target
end sub

sub setPlayerStatus(visible as Boolean, msg as String)
    if m.playerStatus <> invalid then
        m.playerStatus.visible = visible
    end if
    if m.playerStatusLabel <> invalid then
        m.playerStatusLabel.text = msg
    end if
end sub

sub showNowPlaying(item as Object)
    if m.nowPlayingOverlay = invalid then return
    m.nowPlayingOverlay.visible = true

    if m.nowPlayingLabel <> invalid then
        title = ""
        if item <> invalid and item.title <> invalid then title = item.title
        m.nowPlayingLabel.text = title
    end if

    if m.nowPlayingTimer <> invalid then
        m.nowPlayingTimer.control = "stop"
        m.nowPlayingTimer.control = "start"
    end if
end sub

sub onNowPlayingTimerFire()
    if m.nowPlayingOverlay <> invalid then
        m.nowPlayingOverlay.visible = false
    end if
end sub

sub onVideoPosition()
    if m.nowPlayingTime = invalid then return
    if m.video = invalid then return

    dur = m.video.duration
    videoPos = m.video.position
    if dur <= 0 then
        m.nowPlayingTime.text = ""
        return
    end if
    remaining = dur - videoPos
    if remaining < 0 then remaining = 0
    m.nowPlayingTime.text = "-" + formatTime(remaining)
end sub

function formatTime(seconds as Integer) as String
    if seconds < 0 then seconds = 0
    mins = seconds \ 60
    hrs = mins \ 60
    mins = mins mod 60
    secs = seconds mod 60
    if hrs > 0 then
        return hrs.toStr() + ":" + pad2(mins) + ":" + pad2(secs)
    end if
    return mins.toStr() + ":" + pad2(secs)
end function

function pad2(n as Integer) as String
    if n < 10 then return "0" + n.toStr()
    return n.toStr()
end function

sub setErrorOverlay(visible as Boolean, msg as String)
    if m.errorOverlay <> invalid then
        m.errorOverlay.visible = visible
    end if
    if m.errorLabel <> invalid then
        m.errorLabel.text = msg
    end if
end sub

sub onErrorActionSelected(event as Object)
    idx = event.getData()
    if idx = 0 then
        retryPlayback()
    else if idx = 1 then
        m.top.backRequested = true
    end if
end sub

sub retryPlayback()
    if m.video = invalid then return
    if m.video.content = invalid then return
    m.video.control = "play"
    setErrorOverlay(false, "")
end sub

sub saveProgress()
    if m.currentItemId = "" then return
    if m.video = invalid then return
    ProgressService_Save(m.currentItemId, m.video.position, m.video.duration)
    postProgress(false)
end sub

sub postProgress(completed as Boolean)
    if m.currentItemId = "" then return
    if m.video = invalid then return

    userId = loadUserId()
    if userId = "" then return

    host = loadServerHost()
    host = normalizeHostInput(host)
    if host = "" then return

    baseUrl = buildBaseUrlFromHost(host)
    url = baseUrl + "/users/" + userId + "/progress"

    payload = {
        media_file_id: val(m.currentItemId),
        position_seconds: m.video.position,
        duration_seconds: m.video.duration,
        completed: completed
    }

    postJson(url, payload)
end sub

function loadServerHost() as String
    section = CreateObject("roRegistrySection", "GlitchBox")
    if section.Exists("serverHost") then
        return section.Read("serverHost")
    end if
    return ""
end function

function loadUserId() as String
    section = CreateObject("roRegistrySection", "GlitchBox")
    if section.Exists("userId") then
        return section.Read("userId")
    end if
    return ""
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

sub showResumeOverlay(item as Object, position as Integer)
    if m.resumeOverlay = invalid then return
    if m.resumeLabel <> invalid then
        title = ""
        if item <> invalid and item.title <> invalid then title = item.title
        m.resumeLabel.text = "Resume " + title + " at " + formatTime(position) + "?"
    end if
    m.resumeOverlay.visible = true
    if m.resumeActions <> invalid then m.resumeActions.setFocus(true)
end sub

sub hideResumeOverlay()
    if m.resumeOverlay <> invalid then m.resumeOverlay.visible = false
    if m.video <> invalid then m.video.setFocus(true)
end sub

sub onResumeActionSelected(event as Object)
    idx = event.getData()
    if idx = 0 then
        startPendingPlayback(true)
    else if idx = 1 then
        startPendingPlayback(false)
    end if
end sub

sub startPendingPlayback(resume as Boolean)
    if m.pendingContent = invalid then return
    m.video.content = m.pendingContent
    m.video.setFocus(true)
    if resume then
        m.video.seek = m.pendingResumePos
    end if
    m.video.control = "play"
    hideResumeOverlay()
    showTitleOverlay(m.top.playbackItem)
    showNowPlaying(m.top.playbackItem)
    setErrorOverlay(false, "")
    m.pendingContent = invalid
    m.pendingResumePos = 0
end sub

sub showTitleOverlay(item as Object)
    if m.titleOverlay = invalid or m.titleLabel = invalid then return

    title = ""
    if item <> invalid and item.title <> invalid then title = item.title
    m.titleLabel.text = title
    m.titleOverlay.visible = true

    if m.titleTimer <> invalid then
        m.titleTimer.control = "stop"
        m.titleTimer.control = "start"
    end if
end sub

sub onTitleTimerFire()
    if m.titleOverlay <> invalid then
        m.titleOverlay.visible = false
    end if
end sub

sub showActions(visible as Boolean)
    if m.actionOverlay <> invalid then
        m.actionOverlay.visible = visible
    end if
    if visible and m.actionBar <> invalid then
        m.actionBar.setFocus(true)
        resetActionAutoHide()
    else if m.video <> invalid then
        m.video.setFocus(true)
    end if
end sub

sub showQueueOverlay(visible as Boolean)
    if m.queueOverlay = invalid then return
    m.queueOverlay.visible = visible
    if visible then
        updateQueueOverlay()
    end if
end sub

sub updateQueueOverlay()
    if m.queueOverlay = invalid then return
    prevTitle = "-"
    nowTitle = "-"
    nextTitle = "-"

    if m.top.queue <> invalid and m.top.queueIndex <> invalid then
        idx = m.top.queueIndex
        if idx > 0 and idx - 1 < m.top.queue.Count() then
            prev = m.top.queue[idx - 1]
            if prev <> invalid and prev.title <> invalid then prevTitle = prev.title
        end if
        if idx >= 0 and idx < m.top.queue.Count() then
            cur = m.top.queue[idx]
            if cur <> invalid and cur.title <> invalid then nowTitle = cur.title
        end if
        if idx + 1 < m.top.queue.Count() then
            nxt = m.top.queue[idx + 1]
            if nxt <> invalid and nxt.title <> invalid then nextTitle = nxt.title
        end if
    end if

    if m.queuePrev <> invalid then m.queuePrev.text = "Prev: " + prevTitle
    if m.queueNow <> invalid then m.queueNow.text = "Now: " + nowTitle
    if m.queueNext <> invalid then m.queueNext.text = "Next: " + nextTitle
end sub

sub onActionTimerFire()
    showActions(false)
end sub

sub resetActionAutoHide()
    if m.actionTimer <> invalid then
        m.actionTimer.control = "stop"
        m.actionTimer.control = "start"
    end if
end sub

sub playFromStart()
    if m.video = invalid then return
    m.video.seek = 0
    m.video.control = "play"
end sub

sub markWatched()
    if m.currentItemId = "" then return
    postProgress(true)
    ProgressService_Clear(m.currentItemId)
    stopPlayback()
end sub
