sub init()
    m.label = m.top.findNode("label")
    m.focusFrame = m.top.findNode("focusFrame")

    m.top.observeField("itemContent", "onContentChanged")
    m.top.observeField("focusPercent", "onFocusPercentChanged")

    onContentChanged()
end sub

sub onContentChanged()
    item = m.top.itemContent
    if item <> invalid and item.title <> invalid then
        m.label.text = item.title
    else
        m.label.text = ""
    end if
end sub

sub onFocusPercentChanged()
    fp = m.top.focusPercent
    if fp = invalid then fp = 0
    if m.focusFrame <> invalid then m.focusFrame.opacity = fp
end sub
