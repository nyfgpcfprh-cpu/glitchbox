
sub init()
    ' ActionBar is a thin wrapper around a ButtonGroup (or similar) declared in ActionBar.xml.
    m.actions = m.top.findNode("actions")
    if m.actions = invalid then m.actions = m.top.findNode("buttons")
    if m.actions = invalid then m.actions = m.top.findNode("bar")

    ' If the XML didn't declare a focusable node, at least make this component focusable.
    if m.top.hasField("focusable") then m.top.focusable = true

    ' Bind content/labels if provided via itemContent/content.
    if m.top.hasField("itemContent") then
        m.top.observeField("itemContent", "onItemContentChanged")
    else if m.top.hasField("content") then
        m.top.observeField("content", "onItemContentChanged")
    end if

    ' When the row gains focus, push focus into the actual button group.
    if m.top.hasField("itemHasFocus") then
        m.top.observeField("itemHasFocus", "onHasFocusChanged")
    end if

    ' Surface button selection upward if the inner node supports it.
    if m.actions <> invalid then
        if m.actions.hasField("buttonSelected") then
            m.actions.observeField("buttonSelected", "onButtonSelected")
        else if m.actions.hasField("itemSelected") then
            m.actions.observeField("itemSelected", "onButtonSelected")
        end if
    end if

    onItemContentChanged(invalid)
end sub

sub onHasFocusChanged(event as Object)
    if m.actions = invalid then return
    if m.top.itemHasFocus = true then
        m.actions.setFocus(true)
    end if
end sub

sub onItemContentChanged(event as Object)
    ' Attempt to populate the underlying ButtonGroup labels from common payload shapes.
    if m.actions = invalid then return

    c = invalid
    if m.top.hasField("itemContent") then c = m.top.itemContent
    if c = invalid and m.top.hasField("content") then c = m.top.content
    if c = invalid then return

    labels = invalid

    ' Supported shapes:
    '  - { buttons: ["A","B"] }
    '  - { actions: ["A","B"] }
    '  - { items: [ {title:"A"}, {title:"B"} ] }
    '  - ["A","B"]
    if type(c) = "roAssociativeArray" then
        if c.Lookup("buttons", invalid) <> invalid then
            labels = c.buttons
        else if c.Lookup("actions", invalid) <> invalid then
            labels = c.actions
        else if c.Lookup("items", invalid) <> invalid then
            ' items may be AA of labels or content nodes
            items = c.items
            if type(items) = "roArray" then
                tmp = []
                for each it in items
                    if type(it) = "roAssociativeArray" then
                        if it.Lookup("title", invalid) <> invalid then
                            tmp.push(it.title)
                        else if it.Lookup("name", invalid) <> invalid then
                            tmp.push(it.name)
                        else
                            tmp.push("Action")
                        end if
                    else
                        tmp.push(it)
                    end if
                end for
                labels = tmp
            end if
        end if
    else if type(c) = "roArray" then
        labels = c
    end if

    if labels <> invalid and m.actions.hasField("buttons") then
        m.actions.buttons = labels
    end if
end sub

sub onButtonSelected(event as Object)
    ' Bubble selection to parent by setting common fields if present.
    idx = invalid
    if event <> invalid then idx = event.getData()

    if m.top.hasField("selectedIndex") and idx <> invalid then
        m.top.selectedIndex = idx
    end if

    ' Also set selectedLabel if we can.
    if idx <> invalid and m.actions <> invalid and m.actions.hasField("buttons") then
        btns = m.actions.buttons
        if btns <> invalid and idx >= 0 and idx < btns.Count() then
            if m.top.hasField("selectedLabel") then
                m.top.selectedLabel = btns[idx]
            end if
        end if
    end if
end sub

function onKeyEvent(key as String, press as Boolean) as Boolean
    if press = false then return false

    ' Do not allow ActionBar to trap the user on the right side.
    if key = "left" or key = "back" then
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
        ' If not on Home, let the parent scene handle BACK.
        if key = "back" then return false
    end if

    return false
end function
