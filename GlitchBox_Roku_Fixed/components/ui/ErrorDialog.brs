sub init()
    m.label = m.top.findNode("label")
    m.buttons = m.top.findNode("buttons")
    if m.buttons <> invalid then
        m.buttons.buttons = ["OK"]
        m.buttons.observeField("buttonSelected", "onButtonSelected")
    end if
    m.top.observeField("message", "onMessageChanged")
end sub

sub onMessageChanged()
    if m.label <> invalid then
        m.label.text = m.top.message
    end if
end sub

sub onButtonSelected(event as Object)
    m.top.buttonSelected = event.getData()
end sub
