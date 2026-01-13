sub init()
    m.label = m.top.findNode("label")
    m.focusFrame = m.top.findNode("focusFrame")
    m.bg = m.top.findNode("bg")
    m.focusBar = m.top.findNode("focusBar")
    m.lastFocusPercent = 0.0
    m.isSelected = false
    m.itemNode = invalid

    m.top.observeField("itemContent", "onContentChanged")
    m.top.observeField("focusPercent", "onFocusPercentChanged")
    if m.top.hasField("itemHasFocus") then
        m.top.observeField("itemHasFocus", "onItemHasFocusChanged")
    end if

    onContentChanged()
end sub

sub onContentChanged()
    if m.itemNode <> invalid and m.itemNode.hasField("selected") then
        m.itemNode.unobserveField("selected")
    end if

    item = m.top.itemContent
    if item <> invalid and item.title <> invalid then
        m.label.text = item.title
    else
        m.label.text = ""
    end if

    m.itemNode = item
    if m.itemNode <> invalid and m.itemNode.hasField("selected") then
        m.itemNode.observeField("selected", "onSelectedChanged")
        onSelectedChanged()
    end if
end sub

sub onFocusPercentChanged()
    fp = m.top.focusPercent
    if fp = invalid then fp = 0
    m.lastFocusPercent = fp
    applyFocusState((fp > 0.05), fp)
end sub

sub onItemHasFocusChanged()
    hasFocus = (m.top.itemHasFocus = true)
    applyFocusState(hasFocus, m.lastFocusPercent)
end sub

sub applyFocusState(hasFocus as Boolean, fp as Float)
    active = hasFocus or fp > 0.05 or m.isSelected = true

    if m.focusFrame <> invalid then
        if active then
            m.focusFrame.opacity = 1.0
        else
            m.focusFrame.opacity = 0.0
        end if
    end if

    if m.focusBar <> invalid then
        if fp > 0 then
            m.focusBar.opacity = fp
        else if active then
            m.focusBar.opacity = 1.0
        else
            m.focusBar.opacity = 0.0
        end if
    end if

    if m.bg <> invalid then
        if active then
            m.bg.color = "#3E3E3E"
        else
            m.bg.color = "#222222"
        end if
    end if

    if m.label <> invalid then
        if active then
            m.label.color = "#FFFFFF"
        else
            m.label.color = "#D8D8D8"
        end if
    end if
end sub

sub onSelectedChanged()
    if m.itemNode = invalid or m.itemNode.hasField("selected") = false then return
    m.isSelected = (m.itemNode.selected = true)
    applyFocusState(false, m.lastFocusPercent)
end sub
