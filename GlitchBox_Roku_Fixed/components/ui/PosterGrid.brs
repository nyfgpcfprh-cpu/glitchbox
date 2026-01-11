sub init()
    ' PosterGrid is a wrapper around an actual grid node declared in PosterGrid.xml.
    ' We try several common ids so this works even if the XML uses a different name.
    m.grid = m.top.findNode("grid")
    if m.grid = invalid then m.grid = m.top.findNode("posterGrid")
    if m.grid = invalid then m.grid = m.top.findNode("markupGrid")

    ' Keep our inner grid content in sync with this component's content field.
    if m.top.hasField("content") then
        m.top.observeField("content", "onContentChanged")
    end if

    ' When the row gains focus, push focus into the inner grid.
    if m.top.hasField("itemHasFocus") then
        m.top.observeField("itemHasFocus", "onHasFocusChanged")
    end if

    ' If the inner grid exposes itemFocused, keep track of it.
    if m.grid <> invalid and m.grid.hasField("itemFocused") then
        m.grid.observeField("itemFocused", "onItemFocused")
    end if

    m.lastFocused = 0
    onContentChanged(invalid)
end sub

sub onHasFocusChanged(event as Object)
    if m.grid = invalid then return

    if m.top.itemHasFocus = true then
        m.grid.setFocus(true)
    end if
end sub

sub onContentChanged(event as Object)
    if m.grid = invalid then return

    c = invalid
    if m.top.hasField("content") then c = m.top.content
    if c = invalid then return

    if m.grid.hasField("content") then
        m.grid.content = c
    end if
end sub

sub onItemFocused(event as Object)
    if event = invalid then return
    idx = event.getData()
    if idx <> invalid then m.lastFocused = idx
end sub

function onKeyEvent(key as String, press as Boolean) as Boolean
    if press = false then return false

    ' BACK should always escape out of the grid to the left rail when on Home.
    if key = "back" then
        if focusLeftRail() then return true
    end if

    ' LEFT: only escape to left rail when the focused item is in the first column.
    if key = "left" then
        col = 0

        ' Try to compute column using inner grid state
        idx = m.lastFocused
        if m.grid <> invalid and m.grid.hasField("itemFocused") then
            if m.grid.itemFocused <> invalid then idx = m.grid.itemFocused
        end if

        numCols = invalid
        if m.grid <> invalid and m.grid.hasField("numColumns") then numCols = m.grid.numColumns

        if numCols <> invalid and numCols > 0 then
            col = idx mod numCols
        else
            ' If we can't determine columns, treat LEFT as escape (better than trapping)
            col = 0
        end if

        if col = 0 then
            if focusLeftRail() then return true
        end if

        ' not first column: allow the inner grid to handle LEFT
        return false
    end if

    return false
end function

function focusLeftRail() as Boolean
    scene = m.top.getScene()
    if scene = invalid then return false

    home = scene.findNode("homeScene")
    if home <> invalid and home.visible = true then
        nav = home.findNode("navList")
        if nav <> invalid then
            nav.setFocus(true)
            return true
        end if
    end if

    return false
end function
