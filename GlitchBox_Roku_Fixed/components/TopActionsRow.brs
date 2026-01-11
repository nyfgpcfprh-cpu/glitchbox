sub init()
    m.list = m.top.findNode("list")
    if m.list <> invalid then
        m.list.rowItemComponentName = "TopActionItem"
        m.list.observeField("rowItemSelected", "onRowItemSelected")
    end if

    m.top.observeField("actions", "onActionsChanged")
    onActionsChanged()
end sub

sub onActionsChanged()
    actions = m.top.actions

    contentRoot = CreateObject("roSGNode", "ContentNode")
    row = contentRoot.createChild("ContentNode")

    if actions <> invalid then
        for each label in actions
            node = row.createChild("ContentNode")
            node.title = label
        end for
    end if

    if m.list <> invalid then
        m.list.content = contentRoot
    end if
end sub

sub onRowItemSelected(event as Object)
    selection = event.getData()
    if selection = invalid or selection.Count() < 2 then return
    m.top.actionSelected = selection[1]
end sub

function onKeyEvent(key as String, press as Boolean) as Boolean
    if press = false then return false

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