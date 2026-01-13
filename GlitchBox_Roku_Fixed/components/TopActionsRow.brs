sub init()
    ' Defensive: ensure the component itself is visible and has a non-zero height
    if m.top <> invalid then
        m.top.visible = true
        if m.top.hasField("height") then m.top.height = 90
        if m.top.hasField("width") then m.top.width = 1000
        if m.top.hasField("focusable") then m.top.focusable = true
    end if

    m.list = m.top.findNode("list")
    if m.list <> invalid then
        ' Defensive: ensure the internal grid is visible and has non-zero size
        m.list.visible = true
        if m.list.hasField("height") then m.list.height = 80
        if m.list.hasField("width") then m.list.width = 1000

        ' MarkupGrid uses itemComponentName (not rowItemComponentName)
        if m.list.hasField("itemComponentName") then m.list.itemComponentName = "TopActionItem"
        if m.list.hasField("itemSize") then m.list.itemSize = [200, 80]
        if m.list.hasField("itemSpacing") then m.list.itemSpacing = [20, 0]

        m.list.observeField("itemSelected", "onItemSelected")
    end if

    m.selectedIndex = 0
    m.itemCount = 0
    m.contentRoot = invalid

    m.top.observeField("actions", "onActionsChanged")
    if m.top.hasField("hasFocus") then
        m.top.observeField("hasFocus", "onHasFocusChanged")
    end if
    if m.top.hasField("itemHasFocus") then
        m.top.observeField("itemHasFocus", "onItemHasFocusChanged")
    end if
    onActionsChanged()
end sub

sub onActionsChanged()
    actions = m.top.actions

    contentRoot = CreateObject("roSGNode", "ContentNode")

    if actions <> invalid then
        for each label in actions
            node = contentRoot.createChild("ContentNode")
            node.title = label
        end for
    end if

    if m.list <> invalid then
        m.list.content = contentRoot
    end if

    m.contentRoot = contentRoot
    m.itemCount = contentRoot.getChildCount()
    if m.itemCount > 0 then
        if m.top.hasField("selectedIndex") then m.top.selectedIndex = m.selectedIndex
        applySelection()
    end if
end sub

sub onItemSelected(event as Object)
    selection = event.getData()
    if selection = invalid then return
    m.top.actionSelected = selection
end sub

sub onItemHasFocusChanged()
    if m.list = invalid then return
    if m.top.itemHasFocus = true then
        m.list.setFocus(true)
    end if
end sub

sub onHasFocusChanged(event as Object)
    if m.list = invalid then return
    focused = event.getData()
    if focused = true then
        m.list.setFocus(true)
        if m.list.hasField("jumpToItem") then m.list.jumpToItem = 0
    end if
end sub

function moveSelection(delta as Integer) as Boolean
    if m.itemCount <= 0 then return false
    idx = m.selectedIndex + delta
    if idx < 0 then return false
    if idx >= m.itemCount then return false
    setSelection(idx)
    return true
end function

sub setSelection(idx as Integer)
    if m.itemCount <= 0 then return
    if idx < 0 then idx = 0
    if idx >= m.itemCount then idx = m.itemCount - 1
    m.selectedIndex = idx
    if m.top.hasField("selectedIndex") then m.top.selectedIndex = idx
    applySelection()
end sub

sub activateSelection()
    if m.itemCount <= 0 then return
    m.top.actionSelected = m.selectedIndex
end sub

sub applySelection()
    if m.contentRoot = invalid then return
    count = m.contentRoot.getChildCount()
    if count <= 0 then return
    for i = 0 to count - 1
        node = m.contentRoot.getChild(i)
        if node = invalid then exit for
        if node.hasField("selected") = false then node.addField("selected", "bool", false)
        node.selected = (i = m.selectedIndex)
    end for
end sub

function onKeyEvent(key as String, press as Boolean) as Boolean
    if press = false then return false

    ' LEFT -> return to left rail
    if key = "left" then
        scene = m.top.getScene()
        if scene <> invalid then
            home = scene.findNode("homeScene")
            if home <> invalid and home.visible then
                nav = home.findNode("navList")
                if nav <> invalid then
                    nav.setFocus(true)
                    return true
                end if
            end if
        end if
    end if

    ' DOWN -> go into the main rows
    if key = "down" then
        scene = m.top.getScene()
        if scene <> invalid then
            home = scene.findNode("homeScene")
            if home <> invalid and home.visible then
                rows = home.findNode("rows")
                if rows <> invalid then
                    rows.setFocus(true)
                    return true
                end if
            end if
        end if
    end if

    return false
end function
