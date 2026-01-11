sub init()
    m.title = m.top.findNode("title")
    m.grid  = m.top.findNode("grid")

    ' RowList item components receive their data via the built-in itemContent field.
    if m.top.hasField("itemContent") then
        m.top.observeField("itemContent", "onItemContentChanged")
    end if

    ' When this row gains focus, push focus into the grid so LEFT/RIGHT works naturally.
    if m.top.hasField("itemHasFocus") then
        m.top.observeField("itemHasFocus", "onRowFocusChanged")
    end if

    ' Prime initial state if already set
    onItemContentChanged(invalid)
end sub

sub onItemContentChanged(event as Object)
    c = invalid
    if m.top.hasField("itemContent") then c = m.top.itemContent
    if c = invalid then return

    ' Title
    if m.title <> invalid then
        if c.Lookup("title", invalid) <> invalid then
            m.title.text = c.title
        else if c.Lookup("name", invalid) <> invalid then
            m.title.text = c.name
        else
            m.title.text = ""
        end if
    end if

    ' Posters/content
    if m.grid <> invalid then
        ' Try common payload shapes
        if c.Lookup("items", invalid) <> invalid then
            m.grid.content = c.items
        else if c.Lookup("content", invalid) <> invalid then
            m.grid.content = c.content
        else
            ' If the whole object is already content, pass it through
            m.grid.content = c
        end if
    end if
end sub

sub onRowFocusChanged(event as Object)
    if m.grid = invalid then return
    if m.top.itemHasFocus = true then
        m.grid.setFocus(true)
    end if
end sub

function onKeyEvent(key as String, press as Boolean) as Boolean
    if press = false then return false

    ' Escape hatch: allow BACK or LEFT to return to the left rail.
    ' This avoids focus traps when the grid/row consumes LEFT.
    if key = "back" or key = "left" then
        scene = m.top.getScene()
        if scene <> invalid then
            home = scene.findNode("homeScene")
            if home <> invalid and home.visible = true then
                nav = home.findNode("navList")
                if nav <> invalid then
                    nav.setFocus(true)
                    return true
                end if
            end if
        end if
    end if

    return false
end function
