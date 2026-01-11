sub init()
    m.itemTitle = m.top.findNode("itemTitle")
    m.poster = m.top.findNode("poster")
    m.actions = m.top.findNode("actions")
    m.status = m.top.findNode("status")
    m.metaLine = m.top.findNode("metaLine")
    m.description = m.top.findNode("description")
    m.resumeLabel = m.top.findNode("resumeLabel")

    if m.actions <> invalid then
        m.actions.buttons = ["Play", "Resume", "Back"]
        m.actions.observeField("buttonSelected", "onActionSelected")
        m.actions.setFocus(true)
    end if

    m.top.observeField("item", "onItemChanged")
end sub

sub onItemChanged()
    item = m.top.item
    if item = invalid then return

    if m.itemTitle <> invalid then
        m.itemTitle.text = item.title
    end if

    if m.poster <> invalid then
        if item.poster <> invalid and item.poster <> "" then
            m.poster.uri = item.poster
        else
            m.poster.uri = "pkg:/images/icon_side_hd.png"
        end if
    end if

    if m.metaLine <> invalid then
        year = ""
        if item.year <> invalid then year = item.year.toStr()
        runtime = ""
        if item.duration <> invalid then runtime = formatDuration(item.duration)
        rating = ""
        if item.rating <> invalid then rating = item.rating.toStr()
        genre = ""
        if item.genre <> invalid then genre = item.genre
        if item.genres <> invalid and Type(item.genres) = "roArray" and item.genres.Count() > 0 then
            genre = item.genres[0]
        end if
        studio = ""
        if item.studio <> invalid then studio = item.studio
        m.metaLine.text = joinMeta4(year, runtime, rating, genre, studio)
    end if

    if m.description <> invalid then
        if item.description <> invalid and item.description <> "" then
            m.description.text = item.description
        else if item.summary <> invalid and item.summary <> "" then
            m.description.text = item.summary
        else
            m.description.text = ""
        end if
    end if

    if m.resumeLabel <> invalid then
        resumeText = ""
        if item.id <> invalid then
            progress = ProgressService_Load(item.id.toStr())
            if progress <> invalid and progress.position > 0 then
                resumeText = "Resume available at " + formatTime(progress.position)
            end if
        end if
        m.resumeLabel.text = resumeText
    end if

    if m.status <> invalid then
        m.status.text = "Press Play to continue (mock)"
    end if
end sub

sub onActionSelected(event as Object)
    idx = event.getData()
    if idx = 0 then
        m.top.playRequested = m.top.item
        if m.status <> invalid then m.status.text = "Play requested (mock)"
    else if idx = 1 then
        resumeItem = m.top.item
        if resumeItem <> invalid and resumeItem.id <> invalid then
            progress = ProgressService_Load(resumeItem.id.toStr())
            if progress <> invalid and progress.position > 0 then
                resumeItem = {
                    id: resumeItem.id,
                    title: resumeItem.title,
                    poster: resumeItem.poster,
                    url: resumeItem.url,
                    streamFormat: resumeItem.streamFormat,
                    resumePosition: progress.position
                }
            end if
        end if
        m.top.playRequested = resumeItem
        if m.status <> invalid then m.status.text = "Resume requested"
    else if idx = 2 then
        m.top.backRequested = true
    end if
end sub

function formatDuration(value as Dynamic) as String
    if value = invalid then return ""
    seconds = val(value)
    if seconds <= 0 then return ""
    mins = seconds \ 60
    hrs = mins \ 60
    mins = mins mod 60
    if hrs > 0 then
        return hrs.toStr() + "h " + mins.toStr() + "m"
    end if
    return mins.toStr() + "m"
end function

function joinMeta(year as String, runtime as String) as String
    if year <> "" and runtime <> "" then return year + " • " + runtime
    if year <> "" then return year
    if runtime <> "" then return runtime
    return ""
end function

function joinMeta4(year as String, runtime as String, rating as String, genre as String, studio as String) as String
    parts = []
    if year <> "" then parts.push(year)
    if runtime <> "" then parts.push(runtime)
    if rating <> "" then parts.push(rating)
    if genre <> "" then parts.push(genre)
    if studio <> "" then parts.push(studio)

    if parts.Count() = 0 then return ""
    line = parts[0]
    for i = 1 to parts.Count() - 1
        line = line + " • " + parts[i]
    end for
    return line
end function

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

function onKeyEvent(key as String, press as Boolean) as Boolean
    if not press then return false

    if key = "back" then
        m.top.backRequested = true
        return true
    end if

    return false
end function
